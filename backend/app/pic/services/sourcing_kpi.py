"""M05 KPIs (Blueprint 11.5): sourcing cycle time, competitive events %, negotiated savings %, bidders per event, and the measures the second pass adds
(supplier participation, award-to-contract lead time, savings realisation of sourced savings, non-lowest awards).

The four BP KPIs existed in services/kpi.py; three of them were re-defined here because their formulas did not measure what their names say:

* SOURCING_CYCLE   measured from publication to the CREATION of the award decision (the proposal), not to the approved award. It now ends at the audited
                   AWARD transition of the event (the moment the approvals completed).
* COMPETITIVE_EVENTS  looked at event statuses that no event ever has (CLOSED, CONTRACTED, COMPLETED) and counted withdrawn and invalid bids as bidders.
                   It now counts awarded events with at least the minimum number of valid bidders (``sourcing_event.competitive``; older events: two).
* BIDDERS_PER_EVENT counted every bid row, withdrawn and invalid ones included. It now counts distinct suppliers whose bid was evaluated or disqualified.

``kpi.register`` replaces a definition by code, so the dashboards keep their codes, targets and history.
"""
from dataclasses import replace
from decimal import Decimal

from app.pic.services import kpi
from app.pic.services.kpi import DAY, Ctx, Result, mean, pct

AWARD_TS = ("SELECT e.id, a.ts FROM pic.sourcing_event e JOIN LATERAL (SELECT min(ts) AS ts FROM pic.audit_event WHERE object_type = 'SOURCING_EVENT' "
            "AND object_id = e.id AND action = 'AWARD') a ON a.ts IS NOT NULL")
VALID_BIDDERS = ("(SELECT count(DISTINCT b.supplier_id) FROM pic.bid b WHERE b.event_id = e.id AND b.status IN ('UNSEALED', 'SUPERSEDED', 'DISQUALIFIED'))")


def m05_cycle(c: Ctx) -> Result:
    row = c.one(f"SELECT sum(extract(epoch FROM (x.ts - e.published_at))), count(*) FROM pic.sourcing_event e JOIN ({AWARD_TS}) x ON x.id = e.id "
                "WHERE e.published_at IS NOT NULL" + c.when("x.ts"))
    return mean(row[0], row[1], DAY)


def m05_competitive(c: Ctx) -> Result:
    row = c.one(f"SELECT count(*) FILTER (WHERE coalesce(e.competitive, {VALID_BIDDERS} >= 2)), count(*) FROM pic.sourcing_event e JOIN ({AWARD_TS}) x ON x.id = e.id "
                "WHERE e.type <> 'RFI'" + c.when("x.ts"))
    return pct(row[0], row[1])


def m05_bidders(c: Ctx) -> Result:
    row = c.one(f"SELECT sum(n), count(*) FROM (SELECT {VALID_BIDDERS} AS n FROM pic.sourcing_event e WHERE e.published_at IS NOT NULL"
                + c.when("e.published_at") + ") x WHERE n > 0")
    return mean(row[0], row[1])


def m05_participation(c: Ctx) -> Result:
    row = c.one("SELECT (SELECT count(*) FROM (SELECT DISTINCT b.event_id, b.supplier_id FROM pic.bid b JOIN pic.sourcing_event e ON e.id = b.event_id "
                "WHERE b.status IN ('UNSEALED', 'SUPERSEDED', 'DISQUALIFIED', 'SEALED') AND e.published_at IS NOT NULL" + c.when("e.published_at") + ") d), "
                "(SELECT count(*) FROM pic.invitee i JOIN pic.sourcing_event e ON e.id = i.event_id WHERE e.published_at IS NOT NULL" + c.when("e.published_at") + ")")
    return pct(row[0], row[1])


def m05_award_to_contract(c: Ctx) -> Result:
    row = c.one(f"SELECT sum(extract(epoch FROM (k.activated_at - x.ts))), count(*) FROM ({AWARD_TS}) x JOIN LATERAL (SELECT min(activated_at) AS activated_at "
                "FROM pic.contract WHERE source_event_id = x.id AND activated_at IS NOT NULL) k ON k.activated_at IS NOT NULL" + c.when("k.activated_at"))
    return mean(row[0], row[1], DAY)


def m05_savings_link(c: Ctx) -> Result:
    row = c.one("SELECT coalesce(sum(l.amount_minor) FILTER (WHERE l.type = 'REALISED'), 0), coalesce(sum(l.amount_minor) FILTER (WHERE l.type = 'NEGOTIATED'), 0) "
                "FROM pic.savings_ledger_entry l JOIN pic.savings_initiative i ON i.id = l.initiative_id WHERE i.source_event_id IS NOT NULL" + c.when("l.posting_date"))
    return pct(row[0], row[1])


def m05_non_lowest(c: Ctx) -> Result:
    row = c.one("SELECT count(*) FILTER (WHERE d.exceptions @> '[{\"code\": \"NOT_LOWEST\"}]'::jsonb), count(*) FROM pic.award_decision d "
                "WHERE d.status = 'APPROVED'" + c.when("d.created_at"))
    return pct(row[0], row[1])


H, L, I = "HIGHER_BETTER", "LOWER_BETTER", "INFO"
for code, compute in (("M05.SOURCING_CYCLE", m05_cycle), ("M05.COMPETITIVE_EVENTS", m05_competitive), ("M05.BIDDERS_PER_EVENT", m05_bidders)):
    existing = kpi.REGISTRY[code]
    formula = {"M05.SOURCING_CYCLE": "mean time from publication to the approved award (the audited AWARD transition of the event)",
               "M05.COMPETITIVE_EVENTS": "awarded non-RFI events with at least the minimum number of valid bidders / awarded non-RFI events",
               "M05.BIDDERS_PER_EVENT": "distinct bidders whose bid was evaluated or disqualified / published events that received a valid bid"}[code]
    kpi.register(replace(existing, compute=compute, formula=formula, source=existing.source + ", audit_event" if "audit_event" not in existing.source else existing.source))
kpi.register(kpi.KpiDef("M05.SUPPLIER_PARTICIPATION", "M05", "Supplier participation %", "PCT", H, "invited suppliers that bid / invitations of published events",
                        "invitee, bid", 70, 50, compute=m05_participation))
kpi.register(kpi.KpiDef("M05.AWARD_TO_CONTRACT", "M05", "Award-to-contract lead time (days)", "DAYS", L, "mean time from the approved award to the activation of its first contract",
                        "audit_event, contract", 21, 45, compute=m05_award_to_contract))
kpi.register(kpi.KpiDef("M05.SAVINGS_LINK", "M05", "Sourced savings realised %", "PCT", H, "realised savings / negotiated savings of initiatives that came from a sourcing event",
                        "savings_ledger_entry, savings_initiative", 70, 50, compute=m05_savings_link))
kpi.register(kpi.KpiDef("M05.NON_LOWEST_AWARDS", "M05", "Awards to a non-lowest bid %", "PCT", I, "approved awards with a NOT_LOWEST exception (each carries its written rationale) / approved awards",
                        "award_decision", None, None, compute=m05_non_lowest))
