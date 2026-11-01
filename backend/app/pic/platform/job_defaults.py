"""Rule bodies of the wave 1 scheduler, retention, delegation and AI-control rules (seeded for every tenant by seed/reference.py
RULE_SETS and used as the defaults of the code paths when a tenant has no version).

PAYMENT-RUN    daily payment-due job: horizonDays, autoRun (false: propose to the approverRole; true: run what is due today)
MRP-SCHEDULE   scheduled MRP: plants (codes or {plant, mode, materials}), mode, overlapMinutes (a plant with a RUNNING run is skipped)
PRIVACY-RETENTION  categories.<key>.days, purge.dryRun (the purge and archive jobs only report until it is false), audit_archive
DELEGATION     maxDays of one delegation of authority
AI-CONTROL     automatic agent suspension: minFeedback (default 20), window (most recent feedback events considered)
"""

BODIES = {
    "PAYMENT-RUN": ({"horizonDays": 3, "autoRun": False, "approverRole": "FINANCE_CONTROLLER", "slaBusinessDays": 1},
                    "Payment-due job (F7-07): invoices due within horizonDays are proposed to the finance controller; autoRun=true pays "
                    "what is due today through the normal payment run"),
    "MRP-SCHEDULE": ({"plants": [], "mode": "NET_CHANGE", "overlapMinutes": 120},
                     "Scheduled MRP runs (F1): list the plants (or {plant, mode, materials}); empty = no scheduled run"),
    "PRIVACY-RETENTION": ({"categories": {"notification": {"days": 180}, "outbox_event": {"days": 90}, "processed_event": {"days": 90},
                                          "timer": {"days": 180}, "job_run": {"days": 90}, "audit_actor": {"days": 8 * 365}},
                           "purge": {"dryRun": True},
                           "audit_archive": {"hotDays": 730, "batchSize": 5000, "maxEvents": 50000}},
                          "Data retention (DPDP, TD §15): the purge and audit-archive jobs only report until purge.dryRun is set to false; "
                          "add user_profile.days to pseudonymise users deactivated that long"),
    "DELEGATION": ({"maxDays": 90}, "Delegation of authority (out of office): longest period of one delegation"),
    "AI-CONTROL": ({"minFeedback": 20, "window": 100},
                   "AI agents: an agent is suspended automatically when its acceptance rate over the latest window feedback events falls "
                   "below its minimum (70% by default) with at least minFeedback events"),
}
