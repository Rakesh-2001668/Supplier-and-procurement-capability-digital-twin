
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import notifications, procurement, finance, tenant, actions, discovery, contracts, inventory, iot, blockchain, esg, analytics, analytics_hub, supplier_onboarding, supplier_profile, dfsc, simulation, evidence, copilot, command_centre, admin, development, purchasing_p2p, sourcing_clm_savings, planning_mdm, spend_cube_ai_agents, enterprise_admin, industry_templates, specialized_workbenches, bpmn_workflows, unified_approvals, invoice_exceptions, mdm_governance, sealed_bid_mip
from app.routers import notifications, network
from app.api import risk as risk_api
from app.api import supplier

app = FastAPI(title="Supplier Capability Twin API")

# Setup CORS for the Next.js frontend
from app.pic.config import get_settings  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(risk_api.router, prefix="/api/v1/risk", tags=["Risk"])
app.include_router(network.router)
app.include_router(supplier.router)
app.include_router(procurement.router)
app.include_router(finance.router)
app.include_router(tenant.router)
app.include_router(actions.router)
app.include_router(inventory.router)
app.include_router(iot.router, prefix="/api/v1/iot", tags=["IoT"])
app.include_router(blockchain.router, prefix="/api/v1/blockchain", tags=["Blockchain"])
app.include_router(esg.router, prefix="/api/v1/esg", tags=["ESG"])
app.include_router(dfsc.router, prefix="/api/v1/dfsc", tags=["DFSC"])
app.include_router(simulation.router, prefix="/api/v1/simulation", tags=["Monte Carlo Simulation"])
app.include_router(evidence.router, prefix="/api/v1/evidence", tags=["Evidence & Compliance Vault"])
app.include_router(copilot.router, prefix="/api/v1/copilot", tags=["GenAI Procurement Copilot"])
app.include_router(command_centre.router)
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["Analytics"])
app.include_router(analytics_hub.router, prefix="/api/v1/analytics-hub", tags=["Analytics Hub"])
app.include_router(contracts.router)
app.include_router(discovery.router)
app.include_router(supplier_onboarding.router, prefix='/api/v1/suppliers', tags=['Suppliers'])
app.include_router(supplier_profile.router, prefix='/api/v1/suppliers/twin', tags=['Digital Twin'])
app.include_router(admin.router, prefix='/api/v1/admin', tags=['Platform Administration & RBAC'])
app.include_router(development.router, prefix='/api/v1/development', tags=['Supplier Development & CAPA'])
app.include_router(purchasing_p2p.router)
app.include_router(sourcing_clm_savings.router)
app.include_router(planning_mdm.router)
app.include_router(planning_mdm.mdm_router)
app.include_router(spend_cube_ai_agents.router)
app.include_router(spend_cube_ai_agents.agents_router)
app.include_router(enterprise_admin.router)
app.include_router(notifications.router)
app.include_router(industry_templates.router)
app.include_router(specialized_workbenches.router)
app.include_router(bpmn_workflows.router)
app.include_router(unified_approvals.router)
app.include_router(invoice_exceptions.router)
app.include_router(mdm_governance.router)
app.include_router(sealed_bid_mip.router)

@app.get("/health")
def health_check():
    return {"status": "ok"}


# Purchasing Intelligence Cloud: governed F1-F9 workflows on PostgreSQL (Neon) under /v1.
from app.pic.api import install as install_pic  # noqa: E402

install_pic(app)






