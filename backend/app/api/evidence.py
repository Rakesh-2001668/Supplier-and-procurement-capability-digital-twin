from fastapi import APIRouter

router = APIRouter()

@router.get("/queue")
def get_verification_queue():
    return [
        {"id": "doc-1", "doc": "ISO 14001 cert", "supplier": "Salem Light Alloys", "ai_check": "issuer OK", "level": "L2", "flag": None},
        {"id": "doc-2", "doc": "Machine list v3", "supplier": "Kovai Diecast", "ai_check": "count vs photos", "level": "hold", "flag": "integrity"}
    ]
