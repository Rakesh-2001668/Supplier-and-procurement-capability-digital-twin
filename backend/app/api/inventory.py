from fastapi import APIRouter

router = APIRouter()

@router.get("/summary")
def get_inventory_summary():
    return {
        "total_items": 1248,
        "in_stock": 892,
        "low_stock": 186,
        "out_of_stock": 42
    }

@router.get("/items")
def get_inventory_items():
    return [
        {"sku": "BB-6205", "name": "Ball Bearing 6205", "category": "Mechanical", "stock": 450, "reorder": 100, "price": 250.00, "status": "In Stock"},
        {"sku": "IT-LT-5440", "name": "Dell Latitude 5440", "category": "IT Equipment", "stock": 0, "reorder": 10, "price": 78000.00, "status": "Out of Stock"},
        {"sku": "PPE-SH-001", "name": "Safety Helmet", "category": "Safety", "stock": 320, "reorder": 50, "price": 350.00, "status": "In Stock"},
        {"sku": "HL-20L", "name": "Hydraulic Oil 20L", "category": "Chemicals", "stock": 88, "reorder": 30, "price": 4800.00, "status": "In Stock"}
    ]
