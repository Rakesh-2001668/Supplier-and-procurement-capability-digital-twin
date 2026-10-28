from fastapi import APIRouter
import random

router = APIRouter()

@router.get("/historical")
async def get_historical_analytics():
    # 1. Heatmap Data: Supplier Risk Score by Month (Last 6 Months)
    suppliers = ["Global Metals", "TechCorp", "Apex Tooling", "Prime Plastics", "SecureLogistics"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
    
    heatmap_data = []
    for s in suppliers:
        supplier_data = {"supplier": s}
        for m in months:
            # Generate a risk score between 1 and 100 (Higher is riskier)
            base_risk = 30 if s in ["Apex Tooling", "TechCorp"] else 60
            risk = base_risk + random.randint(-20, 30)
            supplier_data[m] = min(max(risk, 0), 100) # Clamp between 0-100
        heatmap_data.append(supplier_data)
        
    # 2. Scatter Data: Defect Rate vs. Lead Time (Supplier clustering)
    scatter_data = []
    for i in range(50):
        # Cluster 1: High perf (low defect, low lead time)
        # Cluster 2: Low perf (high defect, high lead time)
        is_good = random.choice([True, True, False])
        if is_good:
            scatter_data.append({
                "id": f"PO-{1000+i}",
                "lead_time_days": random.uniform(5, 15),
                "defect_rate_pct": random.uniform(0.1, 1.5),
                "category": "High Performer"
            })
        else:
            scatter_data.append({
                "id": f"PO-{1000+i}",
                "lead_time_days": random.uniform(15, 35),
                "defect_rate_pct": random.uniform(2.0, 8.0),
                "category": "Risk Area"
            })
            
    # 3. Time Series Data: 12-Month Quality Trend
    months_12 = ["Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun"]
    trend_data = []
    for m in months_12:
        trend_data.append({
            "month": m,
            "on_time_delivery": random.randint(85, 98),
            "quality_yield": random.randint(90, 99)
        })

    return {
        "heatmap": heatmap_data,
        "scatter": scatter_data,
        "trends": trend_data,
        "months_columns": months
    }
