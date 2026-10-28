"""ASGI entry point: the Purchasing Intelligence Cloud API (/v1) and, outside production, the legacy prototype routers.

The prototype routers (app.routers.*, app.api.*) serve mock data. They are mounted only when PIC_ENABLE_LEGACY_DEMO is true;
it defaults to false with PIC_ENV=production and true elsewhere, so the local demo keeps working.
"""
import logging
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.pic.config import Settings, get_settings
from app.pic.platform import observability

log = logging.getLogger("pic.main")


def _mount_legacy(app: FastAPI) -> None:
    from app.routers import (
        actions, admin, analytics, analytics_hub, blockchain, bpmn_workflows, command_centre, contracts, copilot, development, dfsc,
        discovery, enterprise_admin, esg, evidence, finance, industry_templates, inventory, invoice_exceptions, iot, mdm_governance,
        network, notifications, planning_mdm, procurement, purchasing_p2p, sealed_bid_mip, simulation, sourcing_clm_savings,
        specialized_workbenches, spend_cube_ai_agents, supplier_onboarding, supplier_profile, tenant, unified_approvals,
    )
    from app.api import risk as risk_api
    from app.api import supplier

    legacy = ["Legacy demo"]
    app.include_router(risk_api.router, prefix="/api/v1/risk", tags=legacy)
    app.include_router(network.router, tags=legacy)
    app.include_router(supplier.router, tags=legacy)
    app.include_router(procurement.router, tags=legacy)
    app.include_router(finance.router, tags=legacy)
    app.include_router(tenant.router, tags=legacy)
    app.include_router(actions.router, tags=legacy)
    app.include_router(inventory.router, tags=legacy)
    app.include_router(iot.router, prefix="/api/v1/iot", tags=legacy)
    app.include_router(blockchain.router, prefix="/api/v1/blockchain", tags=legacy)
    app.include_router(esg.router, prefix="/api/v1/esg", tags=legacy)
    app.include_router(dfsc.router, prefix="/api/v1/dfsc", tags=legacy)
    app.include_router(simulation.router, prefix="/api/v1/simulation", tags=legacy)
    app.include_router(evidence.router, prefix="/api/v1/evidence", tags=legacy)
    app.include_router(copilot.router, prefix="/api/v1/copilot", tags=legacy)
    app.include_router(command_centre.router, tags=legacy)
    app.include_router(analytics.router, prefix="/api/v1/analytics", tags=legacy)
    app.include_router(analytics_hub.router, prefix="/api/v1/analytics-hub", tags=legacy)
    app.include_router(contracts.router, tags=legacy)
    app.include_router(discovery.router, tags=legacy)
    app.include_router(supplier_onboarding.router, prefix="/api/v1/suppliers", tags=legacy)
    app.include_router(supplier_profile.router, prefix="/api/v1/suppliers/twin", tags=legacy)
    app.include_router(admin.router, prefix="/api/v1/admin", tags=legacy)
    app.include_router(development.router, prefix="/api/v1/development", tags=legacy)
    app.include_router(purchasing_p2p.router, tags=legacy)
    app.include_router(sourcing_clm_savings.router, tags=legacy)
    app.include_router(planning_mdm.router, tags=legacy)
    app.include_router(planning_mdm.mdm_router, tags=legacy)
    app.include_router(spend_cube_ai_agents.router, tags=legacy)
    app.include_router(spend_cube_ai_agents.agents_router, tags=legacy)
    app.include_router(enterprise_admin.router, tags=legacy)
    app.include_router(notifications.router, tags=legacy)
    app.include_router(industry_templates.router, tags=legacy)
    app.include_router(specialized_workbenches.router, tags=legacy)
    app.include_router(bpmn_workflows.router, tags=legacy)
    app.include_router(unified_approvals.router, tags=legacy)
    app.include_router(invoice_exceptions.router, tags=legacy)
    app.include_router(mdm_governance.router, tags=legacy)
    app.include_router(sealed_bid_mip.router, tags=legacy)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    observability.configure_logging("pic-api", settings.json_logs, settings.log_level)
    docs = settings.docs_enabled
    app = FastAPI(
        title="AlphaHelion Purchasing Intelligence Cloud API",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings

    origins = settings.cors_origin_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["authorization", "content-type", "idempotency-key", "if-match", "x-request-id", "traceparent", "tracestate"],
            expose_headers=["etag", "x-request-id", "retry-after", "traceparent"],
        )

    if settings.legacy_demo_enabled:
        _mount_legacy(app)

        @app.get("/health", include_in_schema=False)
        def health_check():
            return {"status": "ok"}

    # Purchasing Intelligence Cloud: governed F1-F9 workflows on PostgreSQL (Neon) under /v1.
    from app.pic.api import install as install_pic

    install_pic(app)
    log.info("PIC API configured", extra={"fields": {"event": "api_configured", "environment": settings.environment,
                                                     "legacyDemo": settings.legacy_demo_enabled, "apiDocs": docs}})
    return app


app = create_app()
