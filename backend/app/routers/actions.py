from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models.procurement import PurchaseOrder, OrderRequest, Quotation
from app.models.finance import SalesInvoice
from app.models.inventory import InventoryItem, StockTransaction
import uuid

router = APIRouter(prefix="/api/v1/actions", tags=["actions"])

@router.post("/submit-quote/{rfq_id}")
def submit_quote(rfq_id: str, tenant_id: str, db: Session = Depends(get_db)):
    rfq = db.query(OrderRequest).filter(OrderRequest.id == rfq_id).first()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    
    # In a real app, we'd accept price/details in the body.
    rfq.status = "QUOTED"
    db.commit()
    return {"message": "Quote submitted successfully", "rfq_id": rfq_id}

@router.post("/dispatch-order/{po_id}")
def dispatch_order(po_id: str, tenant_id: str, db: Session = Depends(get_db)):
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")
    
    po.status = "DISPATCHED"
    # Deduct inventory for Supplier
    # Mock finding a related inventory item
    inv_item = db.query(InventoryItem).filter(InventoryItem.tenant_id == tenant_id).first()
    if inv_item:
        inv_item.quantity_on_hand -= 100 # Mock deduction
        tx = StockTransaction(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            inventory_item_id=inv_item.id,
            change_quantity=-100,
            reference_type="SALES_ORDER",
            reference_id=po.id
        )
        db.add(tx)
    
    db.commit()
    return {"message": "Order dispatched and inventory deducted", "po_id": po_id}

@router.post("/receive-goods/{po_id}")
def receive_goods(po_id: str, tenant_id: str, db: Session = Depends(get_db)):
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")
    
    po.status = "DELIVERED"
    # Increase inventory for Buyer
    inv_item = db.query(InventoryItem).filter(InventoryItem.tenant_id == tenant_id).first()
    if not inv_item:
        # Create dummy inventory item if none exists for buyer yet
        inv_item = InventoryItem(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            sku="RCV-MOCK-01",
            name="Received Mock Goods",
            quantity_on_hand=0
        )
        db.add(inv_item)
        db.flush()

    inv_item.quantity_on_hand += 100 # Mock receipt addition
    tx = StockTransaction(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        inventory_item_id=inv_item.id,
        change_quantity=100,
        reference_type="GOODS_RECEIPT",
        reference_id=po.id
    )
    db.add(tx)
    db.commit()
    return {"message": "Goods received and inventory updated", "po_id": po_id}


@router.get("/pending-approvals")
def get_pending_approvals(tenant_id: str, db: Session = Depends(get_db)):
    # Returns POs pending approval for this tenant
    pos = db.query(PurchaseOrder).filter(
        PurchaseOrder.tenant_id == tenant_id,
        PurchaseOrder.status == "PENDING_APPROVAL"
    ).all()
    return pos

@router.post("/approve-po/{po_id}")
def approve_po(po_id: str, tenant_id: str, db: Session = Depends(get_db)):
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.tenant_id == tenant_id
    ).first()
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")
        
    po.status = "ISSUED"
    
    # Create the approval record
    from app.models.procurement import POApproval
    approval = POApproval(
        id=str(uuid.uuid4()),
        po_id=po.id,
        approver_id="manager-id", # mocked manager id
        status="APPROVED",
        tenant_id=tenant_id
    )
    db.add(approval)
    db.commit()
    return {"message": "PO Approved and Issued", "po_id": po.id}

@router.post("/reject-po/{po_id}")
def reject_po(po_id: str, tenant_id: str, db: Session = Depends(get_db)):
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.tenant_id == tenant_id
    ).first()
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")
        
    po.status = "REJECTED"
    
    from app.models.procurement import POApproval
    approval = POApproval(
        id=str(uuid.uuid4()),
        po_id=po.id,
        approver_id="manager-id",
        status="REJECTED",
        tenant_id=tenant_id
    )
    db.add(approval)
    db.commit()
    return {"message": "PO Rejected", "po_id": po.id}

from pydantic import BaseModel

class NegotiationRequest(BaseModel):
    message: str
    proposed_amount: float = None

@router.post("/quotations/{quote_id}/negotiate")
def negotiate_quote(quote_id: str, tenant_id: str, payload: NegotiationRequest, db: Session = Depends(get_db)):
    quote = db.query(Quotation).filter(Quotation.id == quote_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quotation not found")
        
    quote.status = "NEGOTIATING"
    
    from app.models.procurement import NegotiationMessage
    msg = NegotiationMessage(
        id=str(uuid.uuid4()),
        quotation_id=quote.id,
        sender_tenant_id=tenant_id,
        message=payload.message,
        proposed_amount=payload.proposed_amount,
        tenant_id=tenant_id # assuming NegotiationMessage is TenantBase, we should link it to the sender's tenant, or maybe the RFQ's tenant. Since TenantBase requires tenant_id, we just use sender's.
    )
    
    db.add(msg)
    db.commit()
    return {"message": "Negotiation sent", "quote_id": quote.id}

@router.get("/quotations/{quote_id}/negotiations")
def get_negotiations(quote_id: str, tenant_id: str, db: Session = Depends(get_db)):
    from app.models.procurement import NegotiationMessage
    msgs = db.query(NegotiationMessage).filter(NegotiationMessage.quotation_id == quote_id).order_by(NegotiationMessage.created_at).all()
    return msgs

@router.post("/quotations/{quote_id}/accept")
def accept_quote(quote_id: str, tenant_id: str, db: Session = Depends(get_db)):
    quote = db.query(Quotation).filter(Quotation.id == quote_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quotation not found")
        
    quote.status = "APPROVED"
    
    # Check if there was a negotiation and update the final amount if proposed
    from app.models.procurement import NegotiationMessage
    last_msg = db.query(NegotiationMessage).filter(
        NegotiationMessage.quotation_id == quote.id,
        NegotiationMessage.proposed_amount.isnot(None)
    ).order_by(NegotiationMessage.created_at.desc()).first()
    
    if last_msg:
        quote.amount = last_msg.proposed_amount
        
    # Generate PO
    po = PurchaseOrder(
        id=str(uuid.uuid4()),
        po_number=f"PO-NEG-{str(uuid.uuid4())[:4]}",
        quotation_id=quote.id,
        supplier_tenant_id=quote.supplier_tenant_id,
        total_amount=quote.amount,
        status="PENDING_APPROVAL",
        tenant_id=tenant_id # the buyer creating it
    )
    db.add(po)
    db.commit()
    return {"message": "Quotation accepted and PO generated", "po_id": po.id}

@router.post('/generate-invoice/{po_id}')
def generate_invoice(po_id: str, tenant_id: str, db: Session = Depends(get_db)):
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail='PO not found')
    inv = SalesInvoice(
        id=str(uuid.uuid4()),
        invoice_number=f'INV-{str(uuid.uuid4())[:6].upper()}',
        supplier_tenant_id=tenant_id,
        buyer_tenant_id=po.tenant_id,
        purchase_order_id=po.id,
        total_amount=po.total_amount,
        status='ISSUED',
        tenant_id=tenant_id
    )
    db.add(inv)
    db.commit()
    return {'message': 'Invoice generated', 'invoice_id': inv.id}
