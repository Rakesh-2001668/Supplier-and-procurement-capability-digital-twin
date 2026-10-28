"""Importing the services registers their event consumers, task handlers, timers and ERP callbacks."""
from app.pic.services import (  # noqa: F401
    admin, contract, forecasting, mdm, order, payables, planning, receiving, requisition, risk, savings, source, sourcing, sourcing_strategy,
    spend, supplier,
)
