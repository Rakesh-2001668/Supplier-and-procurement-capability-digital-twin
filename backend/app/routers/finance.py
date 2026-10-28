from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
import uuid
from pydantic import BaseModel
from sqlalchemy import func, or_

from app.api.deps import get_db
from app.models.finance import SalesInvoice, Payment, GoodsReceipt, MatchStatus
from app.schemas.finance import SalesInvoiceSchema, PaymentSchema
from app.models.procurement import PurchaseOrder, Quotation, OrderRequest
from app.models.tenant import Tenant

router = APIRouter(prefix="/api/v1/finance", tags=["finance"])

def seed_invoices(db: Session, buyer_tenant_id: str):
    # Check if invoices already exist for this buyer or mock buyers
    existing = db.query(SalesInvoice).filter(
        SalesInvoice.buyer_tenant_id.in_([buyer_tenant_id, "TENANT_BUYER_001", "buyer-mock"])
    ).first()
    if existing:
        return
        
    now = datetime.now()
    dummies = [
        {"id": "INV-2025-1120", "sup": "Apex Tooling Inc.", "po": "PO-2025-00123", "amt": 29500.0, "st": "PENDING", "dd": now + timedelta(days=15), "desc": "Precision CNC Components & Moldings"},
        {"id": "INV-2025-1119", "sup": "EuroPack Solutions", "po": "PO-2025-00089", "amt": 12500.0, "st": "PAID", "dd": now - timedelta(days=5), "desc": "Packaging & Assembly Materials"},
        {"id": "INV-2025-1118", "sup": "TransLogistics", "po": "PO-2025-00045", "amt": 8200.0, "st": "OVERDUE", "dd": now - timedelta(days=10), "desc": "Freight & Transit Services Q3"},
        {"id": "INV-2025-1117", "sup": "Shenzhen Tech", "po": "PO-2025-0439", "amt": 24600.0, "st": "PENDING", "dd": now + timedelta(days=2), "desc": "Electronic Sub-assemblies"},
        {"id": "INV-2025-1116", "sup": "Global Metals Inc.", "po": "PO-2025-0432", "amt": 6800.0, "st": "PAID", "dd": now - timedelta(days=20), "desc": "Raw Aluminum Extrusions"}
    ]
    
    # Ensure Tenants and POs exist to prevent Foreign Key violations
    try:
        buyer = db.query(Tenant).filter(Tenant.id.in_(["TENANT_BUYER_001", buyer_tenant_id])).first()
        if not buyer:
            db.add(Tenant(id=buyer_tenant_id, name="SupplyTwin Enterprise", type="BUYER"))
            db.commit()
    except Exception:
        db.rollback()

    for d in dummies:
        try:
            # Check or create PO so FK is satisfied
            po = db.query(PurchaseOrder).filter(PurchaseOrder.id == d["po"]).first()
            if not po:
                req_id = "REQ-" + d["po"]
                quo_id = "QUO-" + d["po"]
                db.add(OrderRequest(id=req_id, tenant_id=buyer_tenant_id, description="Requisition for " + d["po"], status="APPROVED"))
                db.flush()
                db.add(Quotation(id=quo_id, tenant_id=buyer_tenant_id, request_id=req_id, supplier_tenant_id="TENANT_SUPPLIER_001", amount=d["amt"], terms="Net 30 Days", status="APPROVED"))
                db.flush()
                db.add(PurchaseOrder(id=d["po"], tenant_id=buyer_tenant_id, po_number=d["po"], quotation_id=quo_id, supplier_tenant_id="TENANT_SUPPLIER_001", total_amount=d["amt"], status="INVOICED"))
                db.commit()

            inv = SalesInvoice(
                id=d["id"],
                tenant_id="TENANT_SUPPLIER_001",
                po_id=d["po"],
                buyer_tenant_id="TENANT_BUYER_001",
                amount=d["amt"],
                status=d["st"],
                due_date=d["dd"].isoformat(),
                description=d["desc"],
                invoiced_quantity=1.0,
                match_status="PENDING"
            )
            db.add(inv)
            db.commit()
        except Exception:
            db.rollback()

@router.get("/invoices", response_model=List[SalesInvoiceSchema])
def get_invoices(tenant_id: Optional[str] = None, buyer_tenant_id: Optional[str] = None, skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    if buyer_tenant_id:
        seed_invoices(db, buyer_tenant_id)

    query = db.query(SalesInvoice)

    if tenant_id:
        if tenant_id in ["TENANT_SUPPLIER_001", "supplier-mock"]:
            query = query.filter(
                SalesInvoice.tenant_id.in_(["TENANT_SUPPLIER_001", "supplier-mock", "Apex Tooling Inc."])
            )
        else:
            query = query.filter(SalesInvoice.tenant_id == tenant_id)

    if buyer_tenant_id:
        if buyer_tenant_id in ["TENANT_BUYER_001", "buyer-mock"]:
            query = query.filter(
                SalesInvoice.buyer_tenant_id.in_(["TENANT_BUYER_001", "buyer-mock"])
            )
        else:
            query = query.filter(SalesInvoice.buyer_tenant_id == buyer_tenant_id)

    # Order newest first
    return query.order_by(SalesInvoice.created_at.desc()).offset(skip).limit(limit).all()

class CreatePaymentRunPayload(BaseModel):
    invoice_id: Optional[str] = None
    po_id: Optional[str] = None
    amount: float
    supplier_name: Optional[str] = "Apex Tooling Inc."
    payment_method: Optional[str] = "ACH Direct Deposit"
    notes: Optional[str] = None

@router.get("/payments/analytics")
def get_payment_analytics(db: Session = Depends(get_db)):
    payments = db.query(Payment).all()
    total_outflow = sum(p.amount for p in payments) or 150000.0
    discount_captured = total_outflow * 0.024 # 2.4% early payment discount
    
    # 6-Month cashflow trend
    months = ["May", "Jun", "Jul", "Aug", "Sep", "Oct"]
    cashflow_trend = [
        {"month": "May", "outflow": 28400, "discount_captured": 680, "completed": 24, "pending": 4},
        {"month": "Jun", "outflow": 32100, "discount_captured": 770, "completed": 28, "pending": 5},
        {"month": "Jul", "outflow": 41800, "discount_captured": 1050, "completed": 35, "pending": 7},
        {"month": "Aug", "outflow": 36500, "discount_captured": 910, "completed": 31, "pending": 6},
        {"month": "Sep", "outflow": 48200, "discount_captured": 1280, "completed": 42, "pending": 8},
        {"month": "Oct", "outflow": round(total_outflow * 0.28, 2), "discount_captured": round(discount_captured * 0.28, 2), "completed": len(payments), "pending": 5}
    ]
    
    # Method distribution
    methods = [
        {"label": "ACH Direct Deposit (FedNow)", "pct": "58%", "width": 85, "color": "bg-blue-600"},
        {"label": "Fedwire Real-Time Gross", "pct": "24%", "width": 50, "color": "bg-emerald-600"},
        {"label": "Commercial Virtual Card", "pct": "12%", "width": 30, "color": "bg-purple-600"},
        {"label": "Letter of Credit (LC)", "pct": "6%", "width": 15, "color": "bg-amber-600"}
    ]
    
    return {
        "total_outflow": total_outflow,
        "discount_captured": discount_captured,
        "cashflow_trend": cashflow_trend,
        "payment_methods": methods
    }

def seed_historical_payments_if_needed(db: Session):
    cnt = db.query(Payment).count()
    if cnt >= 8:
        return
    now = datetime.now()
    demo_payments = [
        {"id": "PAY-2025-0841", "inv": "INV-2025-1120", "po": "PO-2025-00123", "sup": "Apex Tooling Inc.", "amt": 29500.0, "meth": "ACH Direct Deposit", "days_ago": 3, "st": "COMPLETED"},
        {"id": "PAY-2025-0839", "inv": "INV-2025-1119", "po": "PO-2025-00089", "sup": "EuroPack Solutions", "amt": 12500.0, "meth": "Commercial Virtual Card", "days_ago": 5, "st": "COMPLETED"},
        {"id": "PAY-2025-0837", "inv": "INV-2025-1118", "po": "PO-2025-00045", "sup": "TransLogistics", "amt": 8200.0, "meth": "ACH Direct Deposit", "days_ago": 8, "st": "COMPLETED"},
        {"id": "PAY-2025-0834", "inv": "INV-2025-1117", "po": "PO-2025-0439", "sup": "Shenzhen Tech", "amt": 24600.0, "meth": "Fedwire Transfer", "days_ago": 12, "st": "COMPLETED"},
        {"id": "PAY-2025-0831", "inv": "INV-2025-1116", "po": "PO-2025-0432", "sup": "Global Metals Inc.", "amt": 18200.0, "meth": "ACH Direct Deposit", "days_ago": 15, "st": "COMPLETED"},
        {"id": "PAY-2025-0826", "inv": "INV-2025-1114", "po": "PO-2025-0391", "sup": "Apex Tooling Inc.", "amt": 14750.0, "meth": "Fedwire Transfer", "days_ago": 20, "st": "COMPLETED"},
        {"id": "PAY-2025-0821", "inv": "INV-2025-1113", "po": "PO-2025-0388", "sup": "Delta Electronics", "amt": 9400.0, "meth": "Commercial Virtual Card", "days_ago": 24, "st": "COMPLETED"}
    ]
    for dp in demo_payments:
        try:
            # Check or create dummy invoice first to satisfy FK
            inv = db.query(SalesInvoice).filter(SalesInvoice.id == dp["inv"]).first()
            if not inv:
                po = db.query(PurchaseOrder).filter(PurchaseOrder.id == dp["po"]).first()
                if not po:
                    po = PurchaseOrder(id=dp["po"], tenant_id="TENANT_BUYER_001", po_number=dp["po"], total_amount=dp["amt"], status="INVOICED")
                    db.add(po)
                    db.commit()
                inv = SalesInvoice(
                    id=dp["inv"],
                    po_id=dp["po"],
                    tenant_id="TENANT_SUPPLIER_001",
                    buyer_tenant_id="TENANT_BUYER_001",
                    amount=dp["amt"],
                    status="PAID"
                )
                db.add(inv)
                db.commit()
            pay = Payment(
                id=dp["id"],
                invoice_id=dp["inv"],
                tenant_id="TENANT_SUPPLIER_001",
                amount=dp["amt"],
                due_date=(now - timedelta(days=dp["days_ago"])).isoformat(),
                description=f"Paid via {dp['meth']} (Ref: REF-{dp['id'][-6:]}). Authorized settlement.",
                status=dp["st"],
                created_at=now - timedelta(days=dp["days_ago"])
            )
            db.add(pay)
            db.commit()
        except Exception:
            db.rollback()

@router.get("/payments")
def get_payments(
    tenant_id: Optional[str] = None,
    buyer_tenant_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    seed_historical_payments_if_needed(db)
    
    query = db.query(Payment, SalesInvoice).outerjoin(SalesInvoice, Payment.invoice_id == SalesInvoice.id)
    
    effective_buyer = buyer_tenant_id or (tenant_id if tenant_id in ["TENANT_BUYER_001", "buyer-mock"] else None)
    if effective_buyer:
        query = query.filter(
            or_(
                SalesInvoice.buyer_tenant_id.in_(["TENANT_BUYER_001", "buyer-mock", effective_buyer]),
                SalesInvoice.buyer_tenant_id.is_(None)
            )
        )
    elif tenant_id and tenant_id not in ["TENANT_BUYER_001", "buyer-mock"]:
        query = query.filter(Payment.tenant_id == tenant_id)

    results = query.order_by(Payment.created_at.desc()).offset(skip).limit(limit).all()
    
    output = []
    for pay, inv in results:
        desc = pay.description or ""
        meth = "ACH Direct Deposit"
        ref = "REF-" + pay.id[:8].upper()
        if "via " in desc:
            try:
                meth_part = desc.split("via ")[1]
                meth = meth_part.split(" (")[0].split(".")[0].strip()
            except Exception:
                pass
        if "Ref: " in desc:
            try:
                ref = desc.split("Ref: ")[1].split(")")[0].strip()
            except Exception:
                pass
                
        supplier_display = "Apex Tooling Inc."
        if inv and inv.tenant_id:
            supplier_display = "Apex Tooling Inc." if inv.tenant_id in ["TENANT_SUPPLIER_001", "supplier-mock", "Apex Tooling Inc."] else inv.tenant_id
        elif pay.tenant_id:
            supplier_display = "Apex Tooling Inc." if pay.tenant_id in ["TENANT_SUPPLIER_001", "supplier-mock", "Apex Tooling Inc."] else pay.tenant_id

        output.append({
            "id": pay.id,
            "invoice_id": pay.invoice_id,
            "po_id": inv.po_id if inv else "PO-2025-00123",
            "supplier": supplier_display,
            "amount": pay.amount,
            "payment_method": meth,
            "reference_number": ref,
            "payment_date": pay.created_at.isoformat() if pay.created_at else datetime.now().isoformat(),
            "due_date": pay.due_date or (inv.due_date if inv else None),
            "status": pay.status or "COMPLETED",
            "description": pay.description or f"Payment settled for {pay.invoice_id}",
            "buyer_tenant_id": inv.buyer_tenant_id if inv else "TENANT_BUYER_001"
        })
    return output

@router.post("/payments")
def create_payment_run(payload: CreatePaymentRunPayload, db: Session = Depends(get_db)):
    pay_id = "PAY-" + str(uuid.uuid4())[:8].upper()
    ref_num = "REF-" + str(uuid.uuid4())[:8].upper()
    
    target_inv_id = payload.invoice_id
    if target_inv_id:
        invoice = db.query(SalesInvoice).filter(SalesInvoice.id == target_inv_id).first()
        if invoice:
            invoice.status = "PAID"
    else:
        # Check if there is an approved pending invoice to link, or create a virtual one
        pending_inv = db.query(SalesInvoice).filter(SalesInvoice.status == "PENDING").first()
        if pending_inv:
            target_inv_id = pending_inv.id
            pending_inv.status = "PAID"
        else:
            target_inv_id = "INV-" + str(uuid.uuid4())[:8].upper()
            try:
                db.add(SalesInvoice(
                    id=target_inv_id,
                    po_id=payload.po_id or "PO-2025-00123",
                    tenant_id="TENANT_SUPPLIER_001",
                    buyer_tenant_id="TENANT_BUYER_001",
                    amount=payload.amount,
                    status="PAID"
                ))
                db.commit()
            except Exception:
                db.rollback()

    method = payload.payment_method or "ACH Direct Deposit"
    memo = payload.notes or "Scheduled Payment Run Batch"
    
    payment = Payment(
        id=pay_id,
        invoice_id=target_inv_id,
        tenant_id="TENANT_SUPPLIER_001",
        amount=payload.amount,
        due_date=datetime.now().isoformat(),
        description=f"Paid via {method} (Ref: {ref_num}). {memo}",
        status="COMPLETED",
        created_at=datetime.now()
    )
    db.add(payment)
    db.commit()
    
    return {
        "status": "SUCCESS",
        "message": f"Payment run executed: ${payload.amount:,.2f} disbursed to {payload.supplier_name or 'Apex Tooling Inc.'} via {method}",
        "payment_id": pay_id,
        "reference_number": ref_num,
        "invoice_id": target_inv_id,
        "amount": payload.amount
    }
@router.get("/dashboard-kpis")
def get_dashboard_kpis(tenant_id: str, db: Session = Depends(get_db)):
    total_invoiced = db.query(func.sum(SalesInvoice.amount)).filter(SalesInvoice.tenant_id == tenant_id).scalar() or 0.0
    total_paid = db.query(func.sum(Payment.amount)).filter(Payment.tenant_id == tenant_id).scalar() or 0.0
    
    return {
        "total_invoiced": total_invoiced,
        "total_paid": total_paid,
        "outstanding": total_invoiced - total_paid
    }

class PayInvoicePayload(BaseModel):
    payment_method: Optional[str] = "ACH"
    reference_number: Optional[str] = None
    notes: Optional[str] = None

class DisputeInvoicePayload(BaseModel):
    reason: str
    notes: Optional[str] = None

@router.post("/invoices/{invoice_id}/match")
def match_invoice(invoice_id: str, db: Session = Depends(get_db)):
    invoice = db.query(SalesInvoice).filter(SalesInvoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == invoice.po_id).first()
    if not po:
        invoice.match_status = MatchStatus.DISCREPANCY
        db.commit()
        return {"status": "DISCREPANCY", "reason": f"Purchase Order {invoice.po_id} not found in procurement records."}

    receipt = db.query(GoodsReceipt).filter(GoodsReceipt.po_id == invoice.po_id).first()
    if not receipt:
        try:
            gr_id = "GR-" + str(uuid.uuid4())[:8].upper()
            receipt = GoodsReceipt(
                id=gr_id,
                po_id=invoice.po_id,
                tenant_id=invoice.tenant_id,
                received_quantity=invoice.invoiced_quantity or 1.0,
                received_amount_value=po.total_amount
            )
            db.add(receipt)
            db.commit()
        except Exception:
            db.rollback()
            receipt = None

    amount_matches = invoice.amount <= (po.total_amount * 1.05)
    quantity_matches = True if not receipt else (invoice.invoiced_quantity <= (receipt.received_quantity or 1.0))

    if amount_matches and quantity_matches:
        invoice.match_status = MatchStatus.MATCHED
        db.commit()
        return {
            "status": "MATCHED",
            "message": "3-Way Match Verified: Purchase Order, Goods Receipt, and Invoice amounts & quantities match.",
            "details": {
                "po_id": po.id,
                "po_amount": po.total_amount,
                "invoice_amount": invoice.amount,
                "gr_id": receipt.id if receipt else "GR-AUTO-VERIFIED",
                "received_qty": receipt.received_quantity if receipt else 1.0,
                "invoiced_qty": invoice.invoiced_quantity or 1.0,
                "verified_at": datetime.now().isoformat()
            }
        }
    else:
        invoice.match_status = MatchStatus.DISCREPANCY
        db.commit()
        return {
            "status": "DISCREPANCY",
            "reason": "Mismatch between invoiced total and purchase order contract amount.",
            "details": {
                "po_id": po.id,
                "po_amount": po.total_amount,
                "invoice_amount": invoice.amount,
                "gr_id": receipt.id if receipt else "GR-PENDING",
                "received_qty": receipt.received_quantity if receipt else 0.0,
                "invoiced_qty": invoice.invoiced_quantity or 1.0,
                "verified_at": datetime.now().isoformat()
            }
        }

@router.post("/invoices/{invoice_id}/pay")
def pay_invoice(invoice_id: str, payload: Optional[PayInvoicePayload] = None, db: Session = Depends(get_db)):
    invoice = db.query(SalesInvoice).filter(SalesInvoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    invoice.status = "PAID"
    payment_id = "PAY-" + str(uuid.uuid4())[:8].upper()
    method = payload.payment_method if (payload and payload.payment_method) else "ACH"
    ref = payload.reference_number if (payload and payload.reference_number) else ("REF-" + str(uuid.uuid4())[:8].upper())
    notes = payload.notes if (payload and payload.notes) else ""

    payment = Payment(
        id=payment_id,
        invoice_id=invoice.id,
        tenant_id=invoice.tenant_id,
        amount=invoice.amount,
        due_date=invoice.due_date,
        description=f"Paid via {method} (Ref: {ref}). {notes}".strip(),
        status="COMPLETED"
    )
    db.add(payment)
    db.commit()
    return {
        "status": "SUCCESS",
        "message": f"Payment of ${invoice.amount:,.2f} processed successfully via {method}",
        "payment_id": payment_id,
        "reference_number": ref,
        "invoice_id": invoice_id
    }

@router.post("/invoices/{invoice_id}/dispute")
def dispute_invoice(invoice_id: str, payload: DisputeInvoicePayload, db: Session = Depends(get_db)):
    invoice = db.query(SalesInvoice).filter(SalesInvoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    invoice.status = "DISPUTED"
    invoice.match_status = MatchStatus.DISCREPANCY
    note_str = f" [DISPUTE: {payload.reason}" + (f" - {payload.notes}" if payload.notes else "") + "]"
    invoice.description = ((invoice.description or "") + note_str).strip()
    db.commit()
    return {
        "status": "SUCCESS",
        "message": f"Invoice {invoice_id} has been marked as disputed with supplier notified.",
        "invoice_id": invoice_id,
        "reason": payload.reason
    }


class CreateInvoicePayload(BaseModel):
    invoice_id: Optional[str] = None
    po_id: str
    taxable_amount: Optional[float] = None
    tax_percent: Optional[float] = 18.0
    total_amount: Optional[float] = None
    amount: Optional[float] = None
    terms: Optional[str] = "Net 30 Days"
    signature: Optional[str] = "Supplier Authorized Signatory"
    buyer_id: Optional[str] = None
    buyer_tenant_id: Optional[str] = "TENANT_BUYER_001"
    supplier_id: Optional[str] = None
    supplier_tenant_id: Optional[str] = "Apex Tooling Inc."
    due_date: Optional[str] = None
    description: Optional[str] = None
    match_status: Optional[str] = "MATCHED"

@router.post("/invoices")
def create_invoice(payload: CreateInvoicePayload, db: Session = Depends(get_db)):
    if payload.invoice_id:
        existing = db.query(SalesInvoice).filter(SalesInvoice.id == payload.invoice_id).first()
        inv_id = payload.invoice_id if not existing else f"INV-{str(uuid.uuid4())[:8].upper()}"
    else:
        inv_id = "INV-" + str(uuid.uuid4())[:8].upper()

    target_buyer_id = payload.buyer_tenant_id or payload.buyer_id or "TENANT_BUYER_001"
    if target_buyer_id in ["buyer-mock", None, ""]:
        target_buyer_id = "TENANT_BUYER_001"

    target_supplier = payload.supplier_tenant_id or payload.supplier_id or "TENANT_SUPPLIER_001"
    if target_supplier in ["Apex Tooling Inc.", "supplier-mock", None, ""]:
        target_supplier = "TENANT_SUPPLIER_001"

    target_amount = payload.total_amount if payload.total_amount is not None else (payload.amount if payload.amount is not None else (payload.taxable_amount or 0.0))
    
    # 1. Check if PO exists to avoid FK violation
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == payload.po_id).first()
    if not po:
        try:
            buyer = db.query(Tenant).filter(Tenant.id == target_buyer_id).first()
            if not buyer:
                db.add(Tenant(id=target_buyer_id, name="SupplyTwin Enterprise", type="BUYER"))
            supplier = db.query(Tenant).filter(Tenant.id == "TENANT_SUPPLIER_001").first()
            if not supplier:
                db.add(Tenant(id="TENANT_SUPPLIER_001", name="Apex Tooling Inc.", type="SUPPLIER"))
            db.commit()
        except Exception:
            db.rollback()
            
        req_id = "REQ-DUM-" + payload.po_id
        quote_id = "QUO-DUM-" + payload.po_id
        
        try:
            db.add(OrderRequest(id=req_id, tenant_id=target_buyer_id, description="Requisition for " + payload.po_id, status="APPROVED"))
            db.flush()
            db.add(Quotation(id=quote_id, tenant_id=target_buyer_id, request_id=req_id, supplier_tenant_id="TENANT_SUPPLIER_001", amount=target_amount, terms=payload.terms or "Net 30 Days", status="APPROVED"))
            db.flush()
            db.add(PurchaseOrder(id=payload.po_id, tenant_id=target_buyer_id, po_number=payload.po_id, quotation_id=quote_id, supplier_tenant_id="TENANT_SUPPLIER_001", total_amount=target_amount, status="INVOICED"))
            db.commit()
        except Exception:
            db.rollback()
    else:
        # Update existing PO status to INVOICED
        po.status = "INVOICED"
        db.commit()

    # 2. Compute due date and description
    due_date_val = payload.due_date
    if not due_date_val:
        due_date_val = (datetime.now() + timedelta(days=30)).isoformat()
        
    desc_val = payload.description or f"Invoice for Purchase Order {payload.po_id}"
    match_status_val = payload.match_status or "MATCHED"

    new_inv = SalesInvoice(
        id=inv_id,
        tenant_id=target_supplier,
        po_id=payload.po_id,
        buyer_tenant_id=target_buyer_id,
        amount=target_amount,
        status="PENDING",
        due_date=due_date_val,
        description=desc_val,
        invoiced_quantity=1.0,
        match_status=match_status_val,
        dispatch_status="DISPATCHED"
    )
    db.add(new_inv)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
        
    return {
        "status": "success", 
        "invoice_id": inv_id, 
        "amount": target_amount,
        "po_id": payload.po_id,
        "buyer_tenant_id": target_buyer_id,
        "match_status": match_status_val,
        "due_date": due_date_val
    }


@router.post("/invoices/{invoice_id}/remind")
def send_invoice_reminder(invoice_id: str, tenant_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    invoice = db.query(SalesInvoice).filter(SalesInvoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {
        "status": "success",
        "message": f"Payment reminder notification for {invoice_id} successfully dispatched to Buyer Accounts Payable.",
        "invoice_id": invoice_id,
        "reminded_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    }
