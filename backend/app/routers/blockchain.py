from fastapi import APIRouter
from pydantic import BaseModel
import hashlib
from datetime import datetime

router = APIRouter()

# Mock in-memory blockchain
class Block(BaseModel):
    index: int
    timestamp: str
    data: dict
    previous_hash: str
    hash: str

blockchain = []

def create_block(data: dict):
    previous_block = blockchain[-1] if len(blockchain) > 0 else None
    previous_hash = previous_block.hash if previous_block else "0" * 64
    index = len(blockchain) + 1
    timestamp = datetime.utcnow().isoformat() + "Z"
    
    # Simple hash generation
    block_string = f"{index}{timestamp}{str(data)}{previous_hash}".encode()
    block_hash = hashlib.sha256(block_string).hexdigest()
    
    block = Block(
        index=index,
        timestamp=timestamp,
        data=data,
        previous_hash=previous_hash,
        hash=block_hash
    )
    blockchain.append(block)
    return block

# Genesis Block
create_block({"event": "Genesis", "details": "Blockchain initialized for Supply Chain Network"})

# Some mock traceability blocks
create_block({"event": "Material Sourced", "item_id": "RAW-AL-001", "location": "Mine A, Australia", "esg_compliance": "Verified", "carbon_footprint": "1.2kg CO2"})
create_block({"event": "Quality Inspection", "item_id": "RAW-AL-001", "inspector": "Global Certs", "status": "Passed"})
create_block({"event": "Manufactured", "item_id": "RAW-AL-001", "location": "TechCorp Factory", "status": "Ready for Shipment"})

class SmartContractRequest(BaseModel):
    po_id: str
    invoice_id: str
    amount: float
    supplier_id: str

@router.get("/ledger")
async def get_ledger():
    return {"chain": blockchain, "length": len(blockchain)}

@router.post("/smart-contract/execute")
async def execute_smart_contract(req: SmartContractRequest):
    contract_data = {
        "event": "Smart Contract Executed",
        "contract_type": "Auto-Payment",
        "po_id": req.po_id,
        "invoice_id": req.invoice_id,
        "amount_transferred": req.amount,
        "recipient_wallet": req.supplier_id + "_WALLET",
        "status": "FUNDS_RELEASED"
    }
    
    new_block = create_block(contract_data)
    return {"message": "Smart Contract executed successfully. Block mined.", "block": new_block}

@router.get("/traceability/{item_id}")
async def get_traceability(item_id: str):
    history = [b for b in blockchain if b.data.get("item_id") == item_id]
    if not history:
        b1 = create_block({"event": "Material Sourced", "item_id": item_id, "location": "Facility X", "esg_compliance": "Verified"})
        b2 = create_block({"event": "Manufactured", "item_id": item_id, "location": "Supplier Factory", "carbon_footprint": "2.4kg CO2"})
        history = [b1, b2]
        
    return {"item_id": item_id, "provenance": history}
