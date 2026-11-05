"""M05 event templates and cloning.

A template holds what stays the same from one event to the next of a kind (event type, scoring criteria and weights, award constraints, TCO
overrides, scoring and baseline method, the filter that picks the invitees); an event is created from it with the requirement lines and the dates
of the day. A clone copies a finished event (an awarded one for the renewal, a cancelled one for the re-tender) the same way and keeps the link:
``cloned_from`` on the new event and the CREATED audit entry. Suppliers that are no longer eligible for the category are dropped from the clone
and listed in the result; a clone is always a Draft.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import Criterion, Invitee, SourcingEvent, SourcingTemplate, Supplier
from app.pic.platform import audit
from app.pic.platform.errors import Problem, not_found
from app.pic.services import sourcing
from app.pic.services.common import category_status, principal

KEYS = ("criteria", "constraints", "tco_params", "scoring_method", "baseline_method", "invitee_filter", "auction", "min_bidders", "savings_target_pct")


def save(session: Session, *, code: str, name: str, event_type: str, category: Optional[str], payload: dict) -> SourcingTemplate:
    """Create or replace (a new content for the same code) a template. The criteria must be valid and sum to 100."""
    code = (code or "").strip().upper()
    if not code or len(code) > 40 or not name.strip():
        raise Problem(422, "INVALID_TEMPLATE", "A template needs a code (up to 40 characters) and a name", rule_ref="SRC-TEMPLATE")
    if event_type.upper() not in sourcing.EVENT_TYPES:
        raise Problem(422, "INVALID_TEMPLATE", f"event_type must be one of {', '.join(sourcing.EVENT_TYPES)}", rule_ref="SRC-TEMPLATE")
    unknown = sorted(set(payload) - set(KEYS))
    if unknown:
        raise Problem(422, "INVALID_TEMPLATE", f"Unknown template key(s) {', '.join(unknown)}; allowed: {', '.join(KEYS)}", rule_ref="SRC-TEMPLATE")
    criteria = payload.get("criteria") or []
    sourcing._check_criteria(criteria)
    if criteria and sum(int(c["weight"]) for c in criteria) != 100:
        raise Problem(422, "INVALID_TEMPLATE", f"The template's weights add up to {sum(int(c['weight']) for c in criteria)}, not 100", rule_ref="SRC-WEIGHTS")
    if payload.get("constraints"):
        sourcing._validate_constraints(payload["constraints"])
    row = session.execute(select(SourcingTemplate).where(SourcingTemplate.code == code)).scalar_one_or_none()
    if row is None:
        row = SourcingTemplate(tenant_id=current_tenant(session), code=code, name=name.strip(), event_type=event_type.upper(), category=category,
                               payload=payload, created_by=principal(session).user_id)
        session.add(row)
    else:
        row.name, row.event_type, row.category, row.payload, row.active = name.strip(), event_type.upper(), category, payload, True
    session.flush()
    audit.record(session, "SOURCING_TEMPLATE", row.id, "SAVED", object_ref=code, after={"name": row.name, "type": row.event_type, "category": category, "keys": sorted(payload)})
    return row


def listing(session: Session, category: Optional[str] = None) -> list[dict]:
    query = select(SourcingTemplate).where(SourcingTemplate.active.is_(True)).order_by(SourcingTemplate.code)
    return [{"code": t.code, "name": t.name, "eventType": t.event_type, "category": t.category, "payload": t.payload}
            for t in session.execute(query).scalars() if category is None or t.category in (None, category)]


def _pick_invitees(session: Session, category: str, flt: dict) -> list[dict]:
    found = sourcing.invitee_candidates(session, category, segment=flt.get("segment"), max_risk_score=flt.get("maxRiskScore"),
                                        statuses=["QUALIFIED", "PREFERRED"], exclude_signal_categories=flt.get("excludeSignalCategories"))
    ranked = sorted(found["candidates"], key=lambda c: (c["riskScore"], c["code"]))
    return [{"supplier": c["code"]} for c in ranked[:int(flt.get("max", 5))]]


def create_from_template(session: Session, code: str, *, title: str, category: Optional[str], lines: list[dict], close_at: datetime,
                         invitees: Optional[list[dict]] = None, **overrides) -> SourcingEvent:
    template = session.execute(select(SourcingTemplate).where(SourcingTemplate.code == code.upper(), SourcingTemplate.active.is_(True))).scalar_one_or_none()
    if template is None:
        raise not_found("Sourcing template", code)
    category = category or template.category
    if not category:
        raise Problem(422, "INVALID_EVENT", "Give the category: the template does not fix one", rule_ref="SRC-TEMPLATE")
    if template.category and template.category != category:
        raise Problem(422, "TEMPLATE_CATEGORY", f"Template {template.code} is for {template.category}, not {category}", rule_ref="SRC-TEMPLATE")
    payload = template.payload
    invitees = invitees if invitees is not None else _pick_invitees(session, category, payload.get("invitee_filter") or {})
    if not invitees:
        raise Problem(422, "NO_INVITEES", f"No qualified supplier matches the template's invitation filter for {category}: name the invitees", rule_ref="SRC-INVITE")
    event = sourcing.create_event(
        session, type=template.event_type, title=title, category=category, lines=lines, criteria=payload.get("criteria") or [], invitees=invitees,
        close_at=close_at, constraints=payload.get("constraints") or None, tco_params=payload.get("tco_params") or None,
        scoring_method=payload.get("scoring_method", "LOWEST_RATIO"), baseline_method=overrides.pop("baseline_method", payload.get("baseline_method", "LAST_PRICE")),
        min_bidders=overrides.pop("min_bidders", None) or payload.get("min_bidders"), savings_target_pct=payload.get("savings_target_pct"),
        template_code=template.code, **overrides)
    if payload.get("auction") and event.type == "REVERSE_AUCTION":
        from app.pic.services import auction
        auction.configure(session, event, payload["auction"])
    return event


def clone(session: Session, event: SourcingEvent, *, close_at: datetime, title: Optional[str] = None, lines: Optional[list[dict]] = None) -> dict:
    """A Draft copy of an event: its type, category, criteria and weights, constraints, TCO parameters, scoring and baseline method and the invitees
    that are still eligible. The requirement lines are the same unless ``lines`` gives new ones (a renewal needs a new requisition); a cancelled event's
    lines were released and can be used again, a line another live event holds is refused by the normal event checks."""
    source_lines = lines
    if source_lines is None:
        source_lines = []
        for line in sourcing._lines(session, event):
            sources = sourcing.line_sources(session, line)
            if not sources:
                raise Problem(422, "NO_SOURCE", f"{event.number} line {line.line_no} has no requirement line to clone from: give the lines", rule_ref="SRC-TEMPLATE")
            from app.pic.models import Requisition
            entry = {"annual_qty": str(line.annual_qty), "monthly_qty": str(line.monthly_qty), "lot": line.lot_code, "baseline_price_minor": line.baseline_price_minor,
                     "sources": [{"requisition": session.get(Requisition, rid).number, "line": n} for rid, n in sources]}
            source_lines.append(entry)
    criteria = [{"code": c.code, "name": c.name, "weight": c.weight, "data_source": c.data_source, "min_score": c.min_score}
                for c in session.execute(select(Criterion).where(Criterion.event_id == event.id)).scalars()]
    kept, dropped = [], []
    for inv in session.execute(select(Invitee).where(Invitee.event_id == event.id)).scalars():
        supplier = session.get(Supplier, inv.supplier_id)
        status = category_status(session, supplier.id, event.category)
        if status in sourcing.ELIGIBLE or (status == "CONDITIONAL" and inv.waiver_reason):
            kept.append({"supplier": supplier.code, "waiver_reason": inv.waiver_reason})
        else:
            dropped.append({"supplier": supplier.code, "status": status})
    if not kept:
        raise Problem(422, "NO_INVITEES", f"None of the invitees of {event.number} is eligible for {event.category} any more: name new invitees", rule_ref="SRC-INVITE")
    own_tco = {k: v for k, v in (event.tco_params or {}).items() if not k.startswith("_")}
    clone_ = sourcing.create_event(
        session, type=event.type, title=title or f"{event.title} (re-run)", category=event.category, lines=source_lines, criteria=criteria, invitees=kept, close_at=close_at,
        baseline_method=event.baseline_method or "LAST_PRICE", constraints=dict(event.constraints or {}) or None, tco_params=own_tco or None,
        savings_target_pct=event.savings_target_pct, scoring_method=event.scoring_method, min_bidders=event.min_bidders, cloned_from=event.number,
        template_code=event.template_code)
    if event.type == "REVERSE_AUCTION" and event.auction:
        from app.pic.services import auction
        auction.configure(session, clone_, {k: v for k, v in event.auction.items() if k in auction.SETTING_TYPES})
    return {"event": clone_.number, "clonedFrom": event.number, "invitees": [k["supplier"] for k in kept], "droppedInvitees": dropped,
            "id": str(clone_.id)}
