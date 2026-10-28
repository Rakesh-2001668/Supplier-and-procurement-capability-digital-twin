"""Mount the PIC /v1 API on a FastAPI application."""
from fastapi import FastAPI

import app.pic.services  # noqa: F401  (registers consumers, task handlers, timers)
from app.pic.api import governance, insight, intelligence, lists, order_pay, plan_request, platform, source_contract
from app.pic.platform import errors, http


def install(app: FastAPI) -> None:
    errors.install(app)
    http.install(app)
    for module in (lists, platform, plan_request, source_contract, order_pay, insight, intelligence, governance):
        app.include_router(module.router)
