from fastapi import APIRouter

router = APIRouter()

@router.get("/portfolio/kpis")
def get_kpis():
    return {
        "twins_live": 1284,
        "ecosystem_capability": 68,
        "suppliers_at_risk": 37,
        "open_rfq_matches": 22,
        "dev_plans": 54
    }

@router.get("/portfolio/heatmap")
def get_heatmap():
    return [
        {"process": "Die casting", "readiness": {"strong": 82, "capable": 78, "developing": 64, "gap": 31}},
        {"process": "Machining", "readiness": {"strong": 76, "capable": 74, "developing": 58, "gap": 42}}
    ]
