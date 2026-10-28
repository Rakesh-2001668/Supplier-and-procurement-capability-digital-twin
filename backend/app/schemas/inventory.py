from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class ItemBase(BaseModel):
    sku: str
    name: str
    category: str
    brand: str
    cost: float
    uom: str

class ItemCreate(ItemBase):
    pass

class ItemResponse(ItemBase):
    id: int

    class Config:
        from_attributes = True

class StockMovementBase(BaseModel):
    type: str
    qty: int
    from_loc: str
    to_loc: str
    ref_no: str

class StockMovementCreate(StockMovementBase):
    item_id: int

class StockMovementResponse(StockMovementBase):
    id: int
    item_id: int
    date: datetime

    class Config:
        from_attributes = True
