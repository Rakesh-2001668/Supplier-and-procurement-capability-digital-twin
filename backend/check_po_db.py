from app.core.database import SessionLocal
from app.models.procurement import PurchaseOrder, POApproval
from app.models.inventory import AdvanceShipNotice, StockTransaction, InventoryItem

db = SessionLocal()
pos = db.query(PurchaseOrder).all()
print(f"Total POs: {len(pos)}")
for p in pos:
    print(f"PO: {p.id} | No: {p.po_number} | Sup: {p.supplier_tenant_id} | Amount: ${p.total_amount:,.2f} | Status: {p.status}")

asns = db.query(AdvanceShipNotice).all()
print(f"\nTotal ASNs: {len(asns)}")
for a in asns:
    print(f"ASN: {a.id} | PO: {a.po_id} | Carrier: {a.carrier} | Status: {a.status} | Tracking: {a.tracking_number}")

txs = db.query(StockTransaction).all()
print(f"\nTotal Stock Transactions: {len(txs)}")
for t in txs[-5:]:
    print(f"TX: {t.id} | Item: {t.inventory_item_id} | Chg: {t.change_quantity} | Ref: {t.reference_id} | Type: {t.reference_type}")
