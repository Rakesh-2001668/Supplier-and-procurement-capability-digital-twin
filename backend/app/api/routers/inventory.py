from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.inventory import Item, StockMovement
from app.schemas.inventory import ItemCreate, ItemResponse, StockMovementCreate, StockMovementResponse

router = APIRouter()

@router.get("/items", response_model=List[ItemResponse])
def get_items(db: Session = Depends(get_db)):
    return db.query(Item).all()

@router.post("/items", response_model=ItemResponse)
def create_item(item: ItemCreate, db: Session = Depends(get_db)):
    db_item = Item(**item.model_dump())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@router.get("/movements", response_model=List[StockMovementResponse])
def get_movements(db: Session = Depends(get_db)):
    return db.query(StockMovement).all()

@router.post("/movements", response_model=StockMovementResponse)
def create_movement(movement: StockMovementCreate, db: Session = Depends(get_db)):
    db_movement = StockMovement(**movement.model_dump())
    db.add(db_movement)
    db.commit()
    db.refresh(db_movement)
    return db_movement
