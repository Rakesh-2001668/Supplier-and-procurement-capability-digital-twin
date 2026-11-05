"""Importing the services registers their event consumers, task handlers, timers and ERP callbacks."""
from app.pic.services import (  # noqa: F401
    admin, amendments, auction, bank_files, contract, einvoice, erp_import, forecasting, invitations, master_changes, mdm, notifications, ocr,
    order, payables, planning, policy_sim, privacy, punchout, receiving, requisition, risk, savings, source, sourcing, sourcing_strategy, spend, supplier, transmission,
)
from app.pic.services import delegation, event_consumers, job_handlers, jobs  # noqa: F401,E402  (wave 1 engineer A: scheduler, jobs, delegation of authority)
from app.pic.services import clause_extract, material_changes, rebates, supplier_mgmt  # noqa: F401,E402  (wave 1 engineer C1)
from app.pic.services import (  # noqa: F401,E402  (wave 1 engineer D: industry-template controls)
    ind_construction, ind_general, ind_healthcare, ind_it, ind_kpis, ind_logistics, ind_manufacturing,
)
from app.pic.services import inventory, stock_ledger, stock_reads  # noqa: F401,E402  (inventory: stock ledger, postings, counts, reservations)
from app.pic.services import debit_notes, early_payment, edi_invoice, mandatory, po_controls, request_templates, sales_order  # noqa: F401,E402  (wave 1 engineer B: P2P completion)
from app.pic.services import spend_feed, spend_workflow, spend_forecast, spend_quality, spend_analytics  # noqa: F401,E402  (M01 second pass: cube feed, governance workflows, forecast, data quality, analytics)
from app.pic.services import should_cost, sourcing_analysis, sourcing_handoff, sourcing_kpi, sourcing_notify, sourcing_templates  # noqa: F401,E402  (M05 second pass: should-cost, bid analysis, hand-off, KPIs, notifications, templates)
