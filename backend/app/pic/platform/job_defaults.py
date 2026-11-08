"""Rule bodies of the wave 1 scheduler, retention, delegation and AI-control rules (seeded for every tenant by seed/reference.py
RULE_SETS and used as the defaults of the code paths when a tenant has no version).

PAYMENT-RUN    daily payment-due job: horizonDays, approverRole (autoRun is ignored: humans decide)
MRP-SCHEDULE   scheduled MRP: plants (codes or {plant, mode, materials}), mode, overlapMinutes (a plant with a RUNNING run is skipped)
PRIVACY-RETENTION  categories.<key>.days, purge.dryRun (the purge and archive jobs only report until it is false), audit_archive
DELEGATION     maxDays of one delegation of authority
AI-CONTROL     automatic agent suspension: minFeedback (default 20), window (most recent feedback events considered)
ERP-SYNC       scheduled inbound ERP sync (enabled, system, kinds, retryFailed); off by default
AI-RETRAIN     model drift check and retraining (driftCheck, retrain, retrainAfterDays, retrainOnDrift, autoActivate, models)
"""

BODIES = {
    "PAYMENT-RUN": ({"horizonDays": 3, "autoRun": False, "approverRole": "FINANCE_CONTROLLER", "slaBusinessDays": 1},
                    "Payment-due job (F7-07): invoices due within horizonDays (MSME invoices 45 days after acceptance) and invoices whose early-payment "
                    "discount closes within it are proposed to the finance controller, who decides. autoRun is ignored: the job never pays by itself"),
    "MRP-SCHEDULE": ({"plants": [], "mode": "NET_CHANGE", "overlapMinutes": 120},
                     "Scheduled MRP runs (F1): list the plants (or {plant, mode, materials}); empty = no scheduled run"),
    "PRIVACY-RETENTION": ({"categories": {"notification": {"days": 180}, "outbox_event": {"days": 90}, "processed_event": {"days": 90},
                                          "timer": {"days": 180}, "job_run": {"days": 90}, "audit_actor": {"days": 8 * 365}},
                           "purge": {"dryRun": True},
                           "audit_archive": {"hotDays": 730, "batchSize": 5000, "maxEvents": 50000}},
                          "Data retention (DPDP, TD §15): the purge and audit-archive jobs only report until purge.dryRun is set to false; "
                          "add user_profile.days to pseudonymise users deactivated that long"),
    "DELEGATION": ({"maxDays": 90}, "Delegation of authority (out of office): longest period of one delegation"),
    # Flow fixes (A14): scheduled inbound ERP sync. Off until the tenant switches it on; then each kind runs on its job's schedule from the
    # connector (live OData pull), the file drop or SFTP, whichever services/erp_sync.py finds configured. system null = the ERP-TARGET.
    "ERP-SYNC": ({"enabled": False, "system": None,
                  "kinds": {"MASTERS": True, "STOCK": True, "OPEN_POS": True, "PAYMENT_STATUS": True, "PLANNED_ORDERS": False}, "retryFailed": True},
                 "Scheduled inbound ERP sync (TD §12.1): masters, stock, open POs, payment status, planned orders; off until enabled"),
    # Flow fixes (C6): scheduled model drift check and retraining. A retrained version is registered as CANDIDATE unless autoActivate is true and
    # it passes its evaluation gate (the train functions' gate); a drift alert suspends the active version (ml_registry.check_drift).
    "AI-RETRAIN": ({"driftCheck": True, "retrain": True, "retrainAfterDays": 30, "retrainOnDrift": True, "autoActivate": False,
                    "models": ["demand_forecast", "late_delivery", "invoice_exception_cause"]},
                   "Model drift check (daily) and retraining (weekly) of the M12 models; retrained versions wait as candidates unless autoActivate"),
    "AI-CONTROL": ({"minFeedback": 20, "window": 100},
                   "AI agents: an agent is suspended automatically when its acceptance rate over the latest window feedback events falls "
                   "below its minimum (70% by default) with at least minFeedback events"),
}
