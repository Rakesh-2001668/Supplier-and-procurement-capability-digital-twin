"""Importing the services registers their event consumers, task handlers, timers and ERP callbacks."""
from app.pic.services import (  # noqa: F401
    admin, amendments, auction, bank_files, contract, einvoice, erp_import, forecasting, invitations, master_changes, mdm, notifications, ocr,
    order, payables, planning, policy_sim, privacy, punchout, receiving, requisition, risk, savings, source, sourcing, sourcing_strategy, spend, supplier, transmission,
)
