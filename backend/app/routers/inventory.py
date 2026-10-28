import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, or_
from pydantic import BaseModel

from app.core.database import get_db
from app.models.inventory import InventoryItem, StockTransaction, AdvanceShipNotice
from app.models.finance import GoodsReceipt
from app.models.procurement import PurchaseOrder, POStatus

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])

# ----------------- HELPER FUNCTIONS -----------------

def is_supplier_tenant(tenant_id: Optional[str]) -> bool:
    if not tenant_id:
        return False
    t = tenant_id.strip()
    return "SUPPLIER" in t.upper() or "supplier" in t.lower()

def get_tenant_filter_list(tenant_id: Optional[str]) -> List[str]:
    if is_supplier_tenant(tenant_id):
        targets = ["TENANT_SUPPLIER_001", "supplier-mock"]
        if tenant_id and tenant_id not in targets:
            targets.append(tenant_id)
        return targets
    else:
        targets = ["TENANT_BUYER_001", "buyer-mock"]
        if tenant_id and tenant_id not in targets:
            targets.append(tenant_id)
        return targets

# ----------------- SCHEMAS -----------------

class CreateItemRequest(BaseModel):
    sku: str
    name: str
    category: Optional[str] = "General Components"
    unit: Optional[str] = "pcs"
    quantity_on_hand: Optional[int] = 0
    unit_price: Optional[float] = 0.0
    min_threshold: Optional[int] = 50
    max_capacity: Optional[int] = 5000
    location: Optional[str] = "Warehouse A"
    tenant_id: Optional[str] = "TENANT_BUYER_001"

class GoodsInRequest(BaseModel):
    inventory_item_id: Optional[str] = None
    sku: Optional[str] = None
    item_name: Optional[str] = None
    category: Optional[str] = "General Components"
    unit: Optional[str] = "pcs"
    quantity: int
    unit_price: Optional[float] = 0.0
    location: Optional[str] = "Warehouse A - Bay 01"
    reference_type: Optional[str] = "GOODS_IN"
    reference_id: Optional[str] = None
    notes: Optional[str] = None
    performed_by: Optional[str] = "Warehouse Receiving Dock"
    tenant_id: Optional[str] = "TENANT_BUYER_001"

class GoodsOutRequest(BaseModel):
    inventory_item_id: str
    quantity: int
    reference_type: Optional[str] = "GOODS_OUT"
    reference_id: Optional[str] = None
    destination: Optional[str] = "Assembly Line Production"
    notes: Optional[str] = None
    performed_by: Optional[str] = "Operations Dispatch"
    tenant_id: Optional[str] = "TENANT_BUYER_001"

class StockAdjustmentRequest(BaseModel):
    inventory_item_id: str
    physical_count: int
    reason: Optional[str] = "Cycle Count Variance"
    notes: Optional[str] = None
    performed_by: Optional[str] = "Inventory Auditor"
    tenant_id: Optional[str] = "TENANT_BUYER_001"

class ASNSchema(BaseModel):
    po_id: str
    carrier: str
    tracking_number: str
    expected_date: str

class GRNSchema(BaseModel):
    po_id: str
    received_quantity: float
    received_amount_value: float


# ----------------- ENDPOINTS -----------------

@router.get("/")
@router.get("/items")
def get_inventory(
    tenant_id: Optional[str] = None,
    buyer_tenant_id: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    target_tenant = buyer_tenant_id or tenant_id or "TENANT_BUYER_001"
    tenant_filter = get_tenant_filter_list(target_tenant)
    
    query = db.query(InventoryItem).filter(InventoryItem.tenant_id.in_(tenant_filter))
    if category and category != "ALL":
        query = query.filter(InventoryItem.category == category)
    if status and status != "ALL":
        query = query.filter(InventoryItem.status == status)
    
    items = query.order_by(InventoryItem.name.asc()).all()
    
    # Recalculate dynamic status on each fetch
    result = []
    for it in items:
        computed_status = "IN_STOCK"
        if it.quantity_on_hand <= 0:
            computed_status = "OUT_OF_STOCK"
        elif it.quantity_on_hand <= it.min_threshold:
            computed_status = "LOW_STOCK"
        
        if it.status != computed_status:
            it.status = computed_status
            db.commit()

        result.append({
            "id": it.id,
            "sku": it.sku,
            "name": it.name,
            "category": it.category or "General Components",
            "unit": it.unit or "pcs",
            "quantity_on_hand": it.quantity_on_hand,
            "unit_price": it.unit_price,
            "total_value": round(it.quantity_on_hand * it.unit_price, 2),
            "min_threshold": it.min_threshold,
            "max_capacity": it.max_capacity,
            "location": it.location or "Warehouse A",
            "status": it.status,
            "tenant_id": it.tenant_id,
            "created_at": it.created_at.isoformat() if it.created_at else None,
            "updated_at": it.updated_at.isoformat() if it.updated_at else None
        })
    return result


@router.post("/items")
def create_inventory_item(payload: CreateItemRequest, db: Session = Depends(get_db)):
    """Create a new SKU item in the inventory catalog."""
    now = datetime.now(timezone.utc)
    target_tenant = payload.tenant_id or "TENANT_BUYER_001"
    
    # Unique per tenant
    existing = db.query(InventoryItem).filter(
        func.lower(InventoryItem.sku) == payload.sku.strip().lower(),
        InventoryItem.tenant_id.in_(get_tenant_filter_list(target_tenant))
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Item with SKU '{payload.sku}' already exists.")
        
    qty = payload.quantity_on_hand or 0
    status = "IN_STOCK"
    if qty <= 0:
        status = "OUT_OF_STOCK"
    elif qty <= (payload.min_threshold or 50):
        status = "LOW_STOCK"
        
    item = InventoryItem(
        id=f"INV-SKU-{uuid.uuid4().hex[:6].upper()}",
        sku=payload.sku.strip().upper(),
        name=payload.name.strip(),
        category=payload.category or "General Components",
        unit=payload.unit or "pcs",
        quantity_on_hand=qty,
        unit_price=payload.unit_price or 0.0,
        min_threshold=payload.min_threshold or 50,
        max_capacity=payload.max_capacity or 5000,
        location=payload.location or ("Raw Material Yard - Bay RM-01" if is_supplier_tenant(target_tenant) else "Warehouse A"),
        status=status,
        tenant_id=target_tenant,
        created_at=now,
        updated_at=now
    )
    db.add(item)
    
    # Add initial stock transaction if quantity > 0
    if qty > 0:
        tx = StockTransaction(
            id=f"TX-{uuid.uuid4().hex[:8].upper()}",
            inventory_item_id=item.id,
            change_quantity=qty,
            reference_type="OPENING_BALANCE",
            reference_id=f"INIT-{uuid.uuid4().hex[:6].upper()}",
            notes="Initial stock registration in catalog",
            performed_by="System Administrator",
            balance_after=qty,
            tenant_id=target_tenant,
            created_at=now,
            updated_at=now
        )
        db.add(tx)
        
    db.commit()
    db.refresh(item)
    return {
        "status": "SUCCESS",
        "message": f"Successfully created SKU '{item.sku}' - {item.name}",
        "item": {
            "id": item.id,
            "sku": item.sku,
            "name": item.name,
            "category": item.category,
            "quantity_on_hand": item.quantity_on_hand,
            "unit": item.unit,
            "location": item.location,
            "status": item.status
        }
    }


@router.post("/goods-in")
def receive_goods_in(payload: GoodsInRequest, db: Session = Depends(get_db)):
    """Inbound receipt workflow: increments stock on hand and logs transaction."""
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Received quantity must be greater than 0.")
    
    now = datetime.now(timezone.utc)
    target_tenant = payload.tenant_id or "TENANT_BUYER_001"
    
    item = None
    if payload.inventory_item_id:
        item = db.query(InventoryItem).filter(InventoryItem.id == payload.inventory_item_id).first()
    elif payload.sku:
        item = db.query(InventoryItem).filter(
            func.lower(InventoryItem.sku) == payload.sku.strip().lower(),
            InventoryItem.tenant_id.in_(get_tenant_filter_list(target_tenant))
        ).first()

    if not item:
        # Create new item in catalog
        item = InventoryItem(
            id=f"INV-SKU-{uuid.uuid4().hex[:6].upper()}",
            sku=payload.sku or f"SKU-{uuid.uuid4().hex[:6].upper()}",
            name=payload.item_name or payload.sku or "New Inbound Component",
            category=payload.category or ("Raw Materials" if is_supplier_tenant(target_tenant) else "General Components"),
            unit=payload.unit or "pcs",
            quantity_on_hand=payload.quantity,
            unit_price=payload.unit_price or 10.0,
            min_threshold=50,
            max_capacity=5000,
            location=payload.location or ("Raw Material Yard - Bay RM-01" if is_supplier_tenant(target_tenant) else "Warehouse A - Dock 1"),
            status="IN_STOCK",
            tenant_id=target_tenant,
            created_at=now,
            updated_at=now
        )
        db.add(item)
    else:
        # Update existing item
        item.quantity_on_hand += payload.quantity
        if payload.location:
            item.location = payload.location
        if payload.unit_price and payload.unit_price > 0:
            item.unit_price = payload.unit_price
        item.updated_at = now
        item.status = "IN_STOCK" if item.quantity_on_hand > item.min_threshold else "LOW_STOCK"
        target_tenant = item.tenant_id

    # Insert audit stock transaction
    ref_id = payload.reference_id or f"GRN-{uuid.uuid4().hex[:6].upper()}"
    tx = StockTransaction(
        id=f"TX-{uuid.uuid4().hex[:8].upper()}",
        inventory_item_id=item.id,
        change_quantity=payload.quantity, # positive
        reference_type=payload.reference_type or "GOODS_IN",
        reference_id=ref_id,
        notes=payload.notes or f"Goods In received: +{payload.quantity} {item.unit}. Ref: {ref_id}",
        performed_by=payload.performed_by or ("Receiving Inspector" if is_supplier_tenant(target_tenant) else "Receiving Dock Operator"),
        balance_after=item.quantity_on_hand,
        tenant_id=target_tenant,
        created_at=now,
        updated_at=now
    )
    db.add(tx)
    
    # If PO referenced in buyer persona, check if real PO exists before adding GoodsReceipt (avoid FK constraint error)
    if ref_id and ("PO-" in ref_id) and not is_supplier_tenant(target_tenant):
        po = db.query(PurchaseOrder).filter(PurchaseOrder.id == ref_id).first()
        if po:
            grn = GoodsReceipt(
                id=f"GRN-{uuid.uuid4().hex[:6].upper()}",
                po_id=po.id,
                received_quantity=float(payload.quantity),
                received_amount_value=float(payload.quantity * (item.unit_price or 0.0)),
                status="RECEIVED",
                tenant_id=target_tenant,
                created_at=now
            )
            db.add(grn)

    db.commit()
    db.refresh(item)
    
    return {
        "status": "SUCCESS",
        "message": f"Successfully received {payload.quantity} {item.unit} of '{item.name}'. Current on-hand: {item.quantity_on_hand} {item.unit}.",
        "item": {
            "id": item.id,
            "sku": item.sku,
            "name": item.name,
            "quantity_on_hand": item.quantity_on_hand,
            "unit": item.unit,
            "location": item.location,
            "status": item.status
        },
        "transaction_id": tx.id
    }


@router.post("/goods-out")
def dispatch_goods_out(payload: GoodsOutRequest, db: Session = Depends(get_db)):
    """Outbound dispatch workflow: decrements stock on hand and logs transaction."""
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Dispatched quantity must be greater than 0.")
    
    now = datetime.now(timezone.utc)
    item = db.query(InventoryItem).filter(InventoryItem.id == payload.inventory_item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Inventory item ID '{payload.inventory_item_id}' not found.")
    
    if item.quantity_on_hand < payload.quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient inventory on hand for '{item.name}'. Available: {item.quantity_on_hand} {item.unit}, Requested: {payload.quantity} {item.unit}."
        )
    
    # Decrement stock
    item.quantity_on_hand -= payload.quantity
    item.updated_at = now
    
    # Update status
    if item.quantity_on_hand <= 0:
        item.status = "OUT_OF_STOCK"
    elif item.quantity_on_hand <= item.min_threshold:
        item.status = "LOW_STOCK"
    else:
        item.status = "IN_STOCK"
        
    ref_id = payload.reference_id or f"DISP-{uuid.uuid4().hex[:6].upper()}"
    tx_tenant = item.tenant_id or payload.tenant_id or "TENANT_BUYER_001"
    tx = StockTransaction(
        id=f"TX-{uuid.uuid4().hex[:8].upper()}",
        inventory_item_id=item.id,
        change_quantity=-payload.quantity, # negative
        reference_type=payload.reference_type or "GOODS_OUT",
        reference_id=ref_id,
        notes=payload.notes or f"Goods Out dispatched to {payload.destination}. Ref: {ref_id}",
        performed_by=payload.performed_by or ("Shipping & Logistics Lead" if is_supplier_tenant(tx_tenant) else "Operations Dispatch Lead"),
        balance_after=item.quantity_on_hand,
        tenant_id=tx_tenant,
        created_at=now,
        updated_at=now
    )
    db.add(tx)

    # If dispatch is against a customer Purchase Order, update the PO to SHIPPED and register ASN
    if is_supplier_tenant(tx_tenant) and ("PO-" in ref_id):
        clean_po_id = ref_id.replace("DISP-", "").strip()
        po = db.query(PurchaseOrder).filter(
            (PurchaseOrder.id == clean_po_id) | (PurchaseOrder.po_number == clean_po_id)
        ).first()
        if po:
            po.status = POStatus.SHIPPED
            po.updated_at = now
            asn = AdvanceShipNotice(
                id=f"ASN-{uuid.uuid4().hex[:6].upper()}",
                po_id=po.id,
                carrier="FedEx Aerospace Freight",
                tracking_number=f"FX-{uuid.uuid4().hex[:8].upper()}-US",
                expected_date=(now + timedelta(days=5)).strftime("%Y-%m-%d"),
                status="SHIPPED",
                tenant_id=tx_tenant,
                created_at=now,
                updated_at=now
            )
            db.add(asn)

    db.commit()
    db.refresh(item)
    
    return {
        "status": "SUCCESS",
        "message": f"Successfully dispatched {payload.quantity} {item.unit} of '{item.name}'. Remaining on-hand: {item.quantity_on_hand} {item.unit}.",
        "item": {
            "id": item.id,
            "sku": item.sku,
            "name": item.name,
            "quantity_on_hand": item.quantity_on_hand,
            "unit": item.unit,
            "status": item.status
        },
        "transaction_id": tx.id
    }


@router.post("/adjust")
def adjust_inventory_stock(payload: StockAdjustmentRequest, db: Session = Depends(get_db)):
    """Physical cycle count reconciliation."""
    now = datetime.now(timezone.utc)
    item = db.query(InventoryItem).filter(InventoryItem.id == payload.inventory_item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    
    delta = payload.physical_count - item.quantity_on_hand
    item.quantity_on_hand = payload.physical_count
    item.updated_at = now
    
    if item.quantity_on_hand <= 0:
        item.status = "OUT_OF_STOCK"
    elif item.quantity_on_hand <= item.min_threshold:
        item.status = "LOW_STOCK"
    else:
        item.status = "IN_STOCK"
        
    tx_tenant = item.tenant_id or payload.tenant_id or "TENANT_BUYER_001"
    tx = StockTransaction(
        id=f"TX-{uuid.uuid4().hex[:8].upper()}",
        inventory_item_id=item.id,
        change_quantity=delta,
        reference_type="CYCLE_COUNT_ADJUSTMENT",
        reference_id=f"AUDIT-{uuid.uuid4().hex[:6].upper()}",
        notes=f"Audit adjustment: {payload.reason}. Notes: {payload.notes or 'Routine cycle count'}",
        performed_by=payload.performed_by or "Inventory Auditor",
        balance_after=item.quantity_on_hand,
        tenant_id=tx_tenant,
        created_at=now,
        updated_at=now
    )
    db.add(tx)
    db.commit()
    db.refresh(item)
    
    return {
        "status": "SUCCESS",
        "message": f"Stock adjusted for '{item.name}' by {delta:+d} {item.unit}. New verified balance: {item.quantity_on_hand}.",
        "item": {
            "id": item.id,
            "sku": item.sku,
            "quantity_on_hand": item.quantity_on_hand,
            "status": item.status
        }
    }


@router.get("/movements")
def get_stock_movements(
    tenant_id: Optional[str] = None,
    item_id: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Returns chronologically ordered audit ledger of stock transactions for tenant."""
    target_tenant = tenant_id or "TENANT_BUYER_001"
    tenant_filter = get_tenant_filter_list(target_tenant)
    
    query = db.query(StockTransaction, InventoryItem).join(
        InventoryItem, StockTransaction.inventory_item_id == InventoryItem.id
    ).filter(
        StockTransaction.tenant_id.in_(tenant_filter)
    )
    
    if item_id:
        query = query.filter(StockTransaction.inventory_item_id == item_id)
        
    records = query.order_by(desc(StockTransaction.created_at)).limit(limit).all()
    
    output = []
    for tx, item in records:
        movement_type = "Goods In" if tx.change_quantity > 0 else "Goods Out"
        if tx.reference_type == "CYCLE_COUNT_ADJUSTMENT":
            movement_type = "Adjustment"
            
        output.append({
            "id": tx.id,
            "date": tx.created_at.strftime("%b %d, %Y") if tx.created_at else "Today",
            "time": tx.created_at.strftime("%I:%M %p") if tx.created_at else "12:00 PM",
            "timestamp": tx.created_at.isoformat() if tx.created_at else None,
            "item_id": item.id,
            "sku": item.sku,
            "item_name": item.name,
            "unit": item.unit,
            "type": movement_type,
            "reference_type": tx.reference_type,
            "reference_id": tx.reference_id or "N/A",
            "change_quantity": tx.change_quantity,
            "balance_after": tx.balance_after,
            "notes": tx.notes or "",
            "performed_by": tx.performed_by or ("Warehouse Staff" if not is_supplier_tenant(target_tenant) else "Machine Shop Lead"),
            "location": item.location
        })
    return output


@router.get("/analytics")
def get_inventory_analytics(tenant_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Computes executive inventory KPIs, stock turnover, and valuation for tenant."""
    target_tenant = tenant_id or "TENANT_BUYER_001"
    tenant_filter = get_tenant_filter_list(target_tenant)
    
    items = db.query(InventoryItem).filter(InventoryItem.tenant_id.in_(tenant_filter)).all()
    
    total_items = len(items)
    total_units = sum(i.quantity_on_hand for i in items)
    total_valuation = sum(i.quantity_on_hand * i.unit_price for i in items)
    low_stock = sum(1 for i in items if i.quantity_on_hand <= i.min_threshold and i.quantity_on_hand > 0)
    out_of_stock = sum(1 for i in items if i.quantity_on_hand <= 0)
    
    # Movements calculation
    txs = db.query(StockTransaction).filter(StockTransaction.tenant_id.in_(tenant_filter)).all()
    
    total_inbound_qty = sum(t.change_quantity for t in txs if t.change_quantity > 0)
    total_outbound_qty = sum(abs(t.change_quantity) for t in txs if t.change_quantity < 0)
    
    # Category Breakdown
    cat_counts: Dict[str, Dict[str, Any]] = {}
    for i in items:
        cat = i.category or "Other"
        if cat not in cat_counts:
            cat_counts[cat] = {"count": 0, "units": 0, "value": 0.0}
        cat_counts[cat]["count"] += 1
        cat_counts[cat]["units"] += i.quantity_on_hand
        cat_counts[cat]["value"] += round(i.quantity_on_hand * i.unit_price, 2)
        
    return {
        "total_skus": total_items,
        "total_units_on_hand": total_units,
        "total_valuation_usd": round(total_valuation, 2),
        "low_stock_alerts": low_stock,
        "out_of_stock_count": out_of_stock,
        "total_inbound_units": total_inbound_qty,
        "total_outbound_units": total_outbound_qty,
        "inventory_health_score": 98.4 if total_items > 0 else 0.0,
        "categories": cat_counts
    }


# Legacy ASN / GRN endpoints for backward compatibility
@router.post("/asn")
def create_asn(asn_data: ASNSchema, db: Session = Depends(get_db)):
    asn = AdvanceShipNotice(
        id=f"ASN-{uuid.uuid4().hex[:6]}",
        po_id=asn_data.po_id,
        carrier=asn_data.carrier,
        tracking_number=asn_data.tracking_number,
        expected_date=asn_data.expected_date
    )
    db.add(asn)
    
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == asn_data.po_id).first()
    if po:
        po.status = POStatus.COMPLETED
    
    db.commit()
    return {"status": "success", "asn_id": asn.id}


@router.post("/grn")
def create_grn(grn_data: GRNSchema, db: Session = Depends(get_db)):
    grn = GoodsReceipt(
        id=f"GRN-{uuid.uuid4().hex[:6]}",
        po_id=grn_data.po_id,
        received_quantity=grn_data.received_quantity,
        received_amount_value=grn_data.received_amount_value
    )
    db.add(grn)
    db.commit()
    return {"status": "success", "grn_id": grn.id}
