from fastapi import APIRouter
from datetime import datetime

router = APIRouter()

@router.get("/list")
def list_rfqs():
    return [
        {
            "id": "RFQ-2025-031",
            "title": "Aluminum Housing Components - Q1 2025",
            "status": "Evaluating",
            "priority": "Medium",
            "target_award_date": "2025-03-31"
        },
        {
            "id": "RFQ-2024-001",
            "title": "Brake Housing (AlSi9Cu3)",
            "status": "Matching",
            "priority": "High",
            "target_award_date": "2024-03-15"
        }
    ]

@router.get("/discovery/search")
def search_suppliers(query: str):
    # Mock natural language search response
    return [
        {
            "supplier_id": "SUP-001",
            "name": "ABC Components Pvt Ltd",
            "location": "Chennai, India",
            "match_score": 94,
            "annual_capacity": 120000,
            "trust_score": 91,
            "status": "Verified",
            "capabilities": ["HPDC", "Aluminum Casting", "CNC Machining", "Assembly"],
            "certifications": ["IATF 16949", "ISO 14001"]
        },
        {
            "supplier_id": "SUP-002",
            "name": "XYZ Manufacturing",
            "location": "Pune, India",
            "match_score": 87,
            "annual_capacity": 95000,
            "trust_score": 84,
            "status": "Verified",
            "capabilities": ["HPDC", "Die Casting", "Surface Treatment"],
            "certifications": ["ISO 9001"]
        }
    ]
