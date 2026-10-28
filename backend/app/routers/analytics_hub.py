from fastapi import APIRouter

router = APIRouter()

# --- PHASE 1 ENDPOINTS ---
@router.get("/discovery")
async def get_discovery_analytics():
    return {
        "capability_radar": [
            {"subject": "Quality Control", "Tier 1": 95, "Tier 2": 75, "fullMark": 100},
            {"subject": "Cost Efficiency", "Tier 1": 85, "Tier 2": 90, "fullMark": 100},
            {"subject": "Speed/Lead Time", "Tier 1": 90, "Tier 2": 65, "fullMark": 100},
            {"subject": "ESG Compliance", "Tier 1": 92, "Tier 2": 60, "fullMark": 100},
            {"subject": "Innovation", "Tier 1": 88, "Tier 2": 70, "fullMark": 100}
        ],
        "geographic_distribution": [
            {"region": "North America", "approved": 45, "unapproved": 12},
            {"region": "Europe", "approved": 38, "unapproved": 8},
            {"region": "Asia Pacific", "approved": 65, "unapproved": 25},
            {"region": "South America", "approved": 10, "unapproved": 5}
        ]
    }

@router.get("/approvals")
async def get_approvals_analytics():
    return {
        "rfq_funnel": [
            {"stage": "Drafted", "count": 1200},
            {"stage": "Sent", "count": 1150},
            {"stage": "Quoted", "count": 850},
            {"stage": "Negotiated", "count": 420},
            {"stage": "Awarded", "count": 380}
        ],
        "cycle_time_days": [
            {"department": "Engineering", "avg_days": 4.2},
            {"department": "IT Operations", "avg_days": 2.5},
            {"department": "Facilities", "avg_days": 6.1},
            {"department": "Marketing", "avg_days": 1.8}
        ]
    }

@router.get("/inventory")
async def get_inventory_analytics():
    return {
        "turnover_trend": [
            {"month": "Jan", "actual": 4.1, "target": 4.5},
            {"month": "Feb", "actual": 4.3, "target": 4.5},
            {"month": "Mar", "actual": 4.6, "target": 4.5},
            {"month": "Apr", "actual": 4.2, "target": 4.5},
            {"month": "May", "actual": 4.8, "target": 4.5},
            {"month": "Jun", "actual": 4.7, "target": 4.5}
        ],
        "stockout_risk_matrix": [
            {"sku_category": "Raw Materials", "volume": 8500, "lead_time_var_days": 14, "risk_level": "High"},
            {"sku_category": "Components", "volume": 12000, "lead_time_var_days": 5, "risk_level": "Medium"},
            {"sku_category": "Packaging", "volume": 45000, "lead_time_var_days": 2, "risk_level": "Low"}
        ]
    }

@router.get("/invoices")
async def get_invoice_analytics():
    return {
        "match_status": [
            {"name": "Auto-Matched (Straight Through)", "value": 78},
            {"name": "Manual Review (Tolerance)", "value": 15},
            {"name": "Hard Discrepancy (Exception)", "value": 7}
        ],
        "discrepancy_reasons": [
            {"reason": "Price Mismatch", "count": 145},
            {"reason": "Quantity Shortage", "count": 82},
            {"reason": "Missing GRN", "count": 45},
            {"reason": "Tax Calculation Error", "count": 12}
        ]
    }

# --- PHASE 3 ENDPOINTS ---
@router.get("/payments")
async def get_payments_analytics():
    return {
        "cashflow_trend": [
            {"month": "Jan", "outflow": 120000, "discount_captured": 4500},
            {"month": "Feb", "outflow": 135000, "discount_captured": 5200},
            {"month": "Mar", "outflow": 110000, "discount_captured": 3800},
            {"month": "Apr", "outflow": 145000, "discount_captured": 6100},
            {"month": "May", "outflow": 125000, "discount_captured": 4900},
            {"month": "Jun", "outflow": 160000, "discount_captured": 8200}
        ],
        "payment_timing_scatter": [
            {"days_to_pay": 5, "discount_pct": 2.0, "volume": 45000},
            {"days_to_pay": 10, "discount_pct": 1.5, "volume": 32000},
            {"days_to_pay": 15, "discount_pct": 1.0, "volume": 18000},
            {"days_to_pay": 30, "discount_pct": 0.0, "volume": 85000},
            {"days_to_pay": 45, "discount_pct": 0.0, "volume": 12000}
        ]
    }

@router.get("/iot")
async def get_iot_analytics():
    return {
        "machine_anomalies": [
            {"week": "W1", "temp_spikes": 2, "vib_spikes": 1},
            {"week": "W2", "temp_spikes": 0, "vib_spikes": 3},
            {"week": "W3", "temp_spikes": 5, "vib_spikes": 4},
            {"week": "W4", "temp_spikes": 1, "vib_spikes": 0}
        ],
        "route_deviation": [
            {"route": "Asia-US West", "planned_days": 18, "actual_days": 22},
            {"route": "EU-US East", "planned_days": 12, "actual_days": 13},
            {"route": "SouthAm-EU", "planned_days": 15, "actual_days": 15},
            {"route": "Intra-Asia", "planned_days": 5, "actual_days": 8}
        ]
    }

@router.get("/blockchain")
async def get_blockchain_analytics():
    return {
        "execution_volume": [
            {"month": "Jan", "traditional_ach": 80, "smart_contract": 20},
            {"month": "Feb", "traditional_ach": 75, "smart_contract": 25},
            {"month": "Mar", "traditional_ach": 60, "smart_contract": 40},
            {"month": "Apr", "traditional_ach": 55, "smart_contract": 45},
            {"month": "May", "traditional_ach": 40, "smart_contract": 60},
            {"month": "Jun", "traditional_ach": 30, "smart_contract": 70}
        ],
        "validation_speed": [
            {"node_region": "US-East", "avg_ms": 120},
            {"node_region": "EU-West", "avg_ms": 145},
            {"node_region": "AP-South", "avg_ms": 180},
            {"node_region": "US-West", "avg_ms": 115}
        ]
    }

@router.get("/esg-advanced")
async def get_esg_advanced():
    return {
        "bubble_chart": [
            {"supplier": "Global Metals", "spend_k": 420, "carbon_mt": 1200, "risk": 75},
            {"supplier": "TechCorp Logistics", "spend_k": 850, "carbon_mt": 400, "risk": 45},
            {"supplier": "Apex Tooling", "spend_k": 210, "carbon_mt": 150, "risk": 20},
            {"supplier": "Prime Plastics", "spend_k": 560, "carbon_mt": 890, "risk": 60},
            {"supplier": "SecureTransport", "spend_k": 340, "carbon_mt": 280, "risk": 35}
        ]
    }
