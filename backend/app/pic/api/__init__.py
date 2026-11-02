"""Mount the PIC /v1 API on a FastAPI application."""
from fastapi import FastAPI

import app.pic.services  # noqa: F401  (registers consumers, task handlers, timers)
from app.pic.api import (
    governance, insight, intelligence, lists, master_ops, ops, order_ops, order_pay, plan_request, platform, platform_ops, source_contract,
    source_ops,
)
from app.pic.api import industry  # noqa: E402  (wave 1 engineer D: industry-template controls)
from app.pic.api import wave1_a  # noqa: E402  (wave 1 engineer A: scheduler, delegation, AI switch, audit archive)
from app.pic.api import wave1_c  # noqa: E402  (wave 1 engineer C1: materials, sourcing, contracts, supplier management)
from app.pic.api import enterprise  # noqa: E402  (wave 1 engineer E: workflow designer, field mappings, SoD mitigation, password)
from app.pic.api import erp_ai_ops  # noqa: E402  (wave 1 engineer F: ERP sync, twin, risk feeds, AI registry and gateway)
from app.pic.api import admin_enterprise  # noqa: E402  (M13 enterprise administration: organisation, users, roles, templates)
from app.pic.api import finance  # noqa: E402  (M10 finance completion: periods, TDS, bank results, payment proposal)
from app.pic.api import inventory  # noqa: E402  (M09 inventory: stock reads, stock postings, physical inventory, reservations)
from app.pic.platform import errors, http


def install(app: FastAPI) -> None:
    errors.install(app)
    http.install(app)
    for module in (lists, platform, plan_request, source_contract, order_pay, insight, intelligence, governance, source_ops, order_ops, master_ops,
                   platform_ops, ops):
        app.include_router(module.router)
    app.include_router(industry.router)
    app.include_router(wave1_a.router)
    app.include_router(wave1_c.router)
    app.include_router(enterprise.router)
    app.include_router(erp_ai_ops.router)
    app.include_router(admin_enterprise.router)
    app.include_router(finance.router)
    app.include_router(inventory.router)
