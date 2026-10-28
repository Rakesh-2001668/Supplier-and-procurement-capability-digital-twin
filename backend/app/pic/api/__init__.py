"""Mount the PIC /v1 API on a FastAPI application."""
from fastapi import FastAPI

import app.pic.services  # noqa: F401  (registers consumers, task handlers, timers)
from app.pic.api import (
    governance, insight, intelligence, lists, master_ops, order_ops, order_pay, plan_request, platform, platform_ops, source_contract, source_ops,
)
from app.pic.platform import errors, http


def install(app: FastAPI) -> None:
    errors.install(app)
    http.install(app)
    for module in (lists, platform, plan_request, source_contract, order_pay, insight, intelligence, governance, source_ops, order_ops, master_ops,
                   platform_ops):
        app.include_router(module.router)
