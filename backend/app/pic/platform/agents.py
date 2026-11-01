"""Agent registry, autonomy guard and run log (§13.2, blueprint §25).

Agents act under a role, are limited by autonomy level, value and category, and can be switched off per agent and for the whole
tenant. Every run is stored with its inputs, evidence, model version, output, confidence and the action taken.

Controls (TD §13):
- ``guard`` is the one gate. It checks, in order: the tenant-wide AI switch (``set_ai_switch``), the agent's own kill switch,
  autonomy level, role scope, value and category limits, the drift check (automatic suspension, below) and segregation of duties
  for the action the agent is about to take (rules in ``sod_rule``, evaluated for the agent's own identity and for the person
  who triggered it). ``permit`` wraps it for every call site where an agent acts and logs a DENIED run when it says no.
- Automatic suspension: after each human feedback event (``feedback``) the acceptance rate over the latest ``window`` events is
  checked; with at least ``minFeedback`` events (20) and a rate below the agent's minimum (70% by default, rule AI-CONTROL) the
  agent's kill switch is turned on, the reason and time are stored on the agent, the suspension is audited and ``agent.suspended``
  is emitted (administrators are notified). Turning the switch off again (``set_kill_switch``) restarts the feedback window.
"""
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, current_user
from app.pic.models import ActionLog, Agent, AgentRun, TenantFlag
from app.pic.platform import audit, clock, outbox, sod
from app.pic.platform.auth import ROLE_SCOPES
from app.pic.platform.errors import Problem, not_found

LEVELS = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4}
AI_SWITCH = "AI_SWITCH"
MIN_FEEDBACK_DEFAULT = 20
WINDOW_DEFAULT = 100

# Blueprint Table 25 (default autonomy).
CATALOGUE = [
    ("DEMAND_SENSING", "Demand Sensing Agent", "MRP", "Detects forecast bias and demand shifts; proposes forecast overrides", "L1", "MRP_CONTROLLER", None),
    ("MRP_EXCEPTION", "MRP Exception Agent", "MRP", "Ranks exceptions by value at risk; drafts reschedule actions", "L2", "MRP_CONTROLLER", None),
    ("GUIDED_BUYING", "Guided Buying Agent", "REQ", "Finds contract/catalogue matches, fills account assignment", "L2", "REQUESTER", None),
    ("MATERIAL_DEDUP", "Material Dedup Agent", "MDM", "Scores duplicates, proposes classification", "L2", "MDM_STEWARD", None),
    ("SPEND_CLASSIFICATION", "Spend Classification Agent", "SPD", "Classifies lines to taxonomy with confidence", "L3", "CATEGORY_MANAGER", None),
    ("SOURCING_STRATEGY", "Sourcing Strategy Agent", "SRC", "Recommends event type, invitees, scoring weights", "L1", "CATEGORY_MANAGER", None),
    ("BID_ANALYSIS", "Bid Analysis Agent", "SRC", "Normalises bids, TCO, should-cost delta, award scenarios", "L2", "CATEGORY_MANAGER", None),
    ("CONTRACT_REVIEW", "Contract Review Agent", "CLM", "Redlines vs playbook, risk score, obligations extraction", "L2", "CONTRACT_MANAGER", None),
    ("PO_VALIDATION", "PO Validation Agent", "PO", "Price/risk/split checks; PO risk score", "L3", "BUYER", None),
    ("TOUCHLESS_PO", "Touchless PO Agent", "PO", "Creates and releases POs meeting touchless rules", "L4", "BUYER", 250_000_000),
    ("EXPEDITING", "Expediting Agent", "PO", "Predicts late delivery; drafts supplier follow-ups", "L2", "BUYER", None),
    ("INVOICE_EXCEPTION", "Invoice Exception Agent", "INV", "Explains exception cause; proposes credit note/approval", "L2", "AP_CLERK", None),
    ("SUPPLIER_RISK", "Supplier Risk Agent", "SLM", "Monitors risk signals; proposes mitigation", "L1", "SUPPLIER_MANAGER", None),
    ("SAVINGS_VALIDATION", "Savings Validation Agent", "SAV", "Computes realised savings from posted invoices", "L3", "CATEGORY_MANAGER", None),
    ("COPILOT", "Procurement Copilot", "AIX", "Answers questions with evidence, confidence and permission (answer contract)", "L1", "CATEGORY_MANAGER", None),
]


def get(session: Session, code: str) -> Agent:
    return session.execute(select(Agent).where(Agent.code == code)).scalar_one()


def exists(session: Session, code: str) -> bool:
    """Tenants bootstrapped before an agent was added to the catalogue have no row for it."""
    return session.execute(select(Agent.id).where(Agent.code == code)).first() is not None


def agent_actor_id(session: Session, code: str) -> uuid.UUID:
    """The identity an agent acts under (same derivation as ``auth.agent_principal``), used for segregation-of-duties history."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"pic-agent:{current_tenant(session)}:{code}")


# ---------------------------------------------------------------- tenant-wide switch
def ai_enabled(session: Session) -> tuple[bool, Optional[str]]:
    flag = session.execute(select(TenantFlag).where(TenantFlag.key == AI_SWITCH)).scalar_one_or_none()
    if flag is None:
        return True, None
    return bool((flag.value or {}).get("enabled", True)), flag.reason


def ai_switch_state(session: Session) -> dict:
    flag = session.execute(select(TenantFlag).where(TenantFlag.key == AI_SWITCH)).scalar_one_or_none()
    enabled, reason = ai_enabled(session)
    return {"enabled": enabled, "reason": reason, "changedAt": (flag.updated_at or flag.created_at).isoformat() if flag else None,
            "changedBy": str(flag.changed_by) if flag and flag.changed_by else None, "version": flag.row_version if flag else 0}


def set_ai_switch(session: Session, enabled: bool, reason: str) -> dict:
    """Switch every AI agent of the tenant off (or on again). Honoured by ``guard``, so by every agent call; audited."""
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for switching AI " + ("on" if enabled else "off"), rule_ref="AI-CONTROL")
    user = current_user(session)
    flag = session.execute(select(TenantFlag).where(TenantFlag.key == AI_SWITCH).with_for_update()).scalar_one_or_none()
    before = bool((flag.value or {}).get("enabled", True)) if flag is not None else True
    if flag is None:
        flag = TenantFlag(tenant_id=current_tenant(session), key=AI_SWITCH, value={"enabled": enabled}, reason=reason, changed_by=user, created_by=user)
        session.add(flag)
    else:
        flag.value, flag.reason, flag.changed_by = {"enabled": enabled}, reason, user
    session.flush()
    audit.record(session, "TENANT_AI", flag.id, "AI_SWITCHED_ON" if enabled else "AI_SWITCHED_OFF", object_ref="AI_SWITCH",
                 before={"enabled": before}, after={"enabled": enabled}, reason=reason, rule_set_version="AI-CONTROL")
    outbox.emit(session, "ai.switch.changed", "TENANT_AI", flag.id, "AI_SWITCH", {"enabled": enabled, "reason": reason})
    return ai_switch_state(session)


# ---------------------------------------------------------------- acceptance and automatic suspension
def _control(session: Session) -> dict:
    from app.pic.platform import rules  # local import: rules is a sibling with no dependency on agents
    try:
        body = rules.resolve(session, "AI-CONTROL").body or {}
    except Problem:
        body = {}
    return {"minFeedback": int(body.get("minFeedback", MIN_FEEDBACK_DEFAULT)), "window": int(body.get("window", WINDOW_DEFAULT))}


def acceptance_stats(session: Session, code: str) -> dict:
    """Acceptance over the latest ``window`` feedback events since the last reset: {events, accepted, rate (None below minFeedback)}."""
    agent = get(session, code)
    control = _control(session)
    query = select(AgentRun.human_feedback).where(AgentRun.agent_code == code, AgentRun.human_feedback.is_not(None))
    if agent.acceptance_reset_at is not None:
        query = query.where(AgentRun.created_at >= agent.acceptance_reset_at)
    rows = session.execute(query.order_by(AgentRun.created_at.desc()).limit(control["window"])).scalars().all()
    accepted = sum(1 for fb in rows if fb == "ACCEPTED")
    rate = Decimal(accepted) / Decimal(len(rows)) if len(rows) >= control["minFeedback"] else None
    return {"events": len(rows), "accepted": accepted, "rate": rate, "minFeedback": control["minFeedback"]}


def acceptance_rate(session: Session, code: str) -> Optional[Decimal]:
    return acceptance_stats(session, code)["rate"]


def evaluate_suspension(session: Session, code: str) -> bool:
    """Suspend the agent when its acceptance has drifted below its minimum. Returns True when it was suspended just now."""
    agent = get(session, code)
    if agent.kill_switch:
        return False
    stats = acceptance_stats(session, code)
    minimum = Decimal(str(agent.min_acceptance_rate))
    if stats["rate"] is None or stats["rate"] >= minimum:
        return False
    agent.kill_switch, agent.suspended_at, agent.suspended_by = True, clock.now(), "AUTO"
    agent.suspension_reason = (f"acceptance rate {stats['rate']:.0%} over the latest {stats['events']} feedback events is below the "
                               f"minimum {minimum:.0%}")
    session.flush()
    audit.record(session, "AGENT", agent.id, "AGENT_AUTO_SUSPENDED", object_ref=agent.code, reason=agent.suspension_reason,
                 after={"acceptance": str(stats["rate"]), "events": stats["events"], "minimum": str(minimum)}, rule_set_version="AI-CONTROL")
    outbox.emit(session, "agent.suspended", "AGENT", agent.id, agent.code,
                {"agent": agent.code, "reason": agent.suspension_reason, "acceptance": float(stats["rate"]), "events": stats["events"],
                 "automatic": True})
    return True


def set_kill_switch(session: Session, code: str, on: bool, reason: str) -> Agent:
    """Manual switch (agents:manage). Turning it off also restarts the feedback window, so an agent suspended for drift is not
    suspended again by the very events that suspended it."""
    agent = session.execute(select(Agent).where(Agent.code == code.upper())).scalar_one_or_none()
    if agent is None:
        raise not_found("Agent", code)
    was_on = agent.kill_switch
    agent.kill_switch = on
    if on:
        agent.suspended_at, agent.suspended_by, agent.suspension_reason = clock.now(), f"u:{current_user(session)}", reason
    else:
        agent.suspended_at = agent.suspended_by = agent.suspension_reason = None
        agent.acceptance_reset_at = clock.now()
    session.flush()
    audit.record(session, "AGENT", agent.id, "KILL_SWITCH_ON" if on else "KILL_SWITCH_OFF", object_ref=agent.code, reason=reason,
                 before={"killSwitch": was_on}, after={"killSwitch": on})
    return agent


# ---------------------------------------------------------------- the gate
def guard(session: Session, code: str, *, required_level: str, scope: Optional[str] = None,
          value_minor: Optional[int] = None, category: Optional[str] = None, sod_action: Optional[str] = None,
          sod_refs: Optional[dict] = None) -> tuple[bool, Optional[str]]:
    enabled, switch_reason = ai_enabled(session)
    if not enabled:
        return False, "AI is switched off for this organisation" + (f": {switch_reason}" if switch_reason else "")
    agent = get(session, code)
    if agent.kill_switch:
        return False, "kill switch is on" + (f" ({agent.suspension_reason})" if agent.suspension_reason else "")
    if LEVELS[agent.autonomy_level] < LEVELS[required_level]:
        return False, f"autonomy {agent.autonomy_level} is below required {required_level}"
    if scope and scope not in ROLE_SCOPES.get(agent.run_as_role, set()):
        return False, f"role {agent.run_as_role} lacks scope {scope}"
    if value_minor is not None and agent.value_limit_minor is not None and value_minor > agent.value_limit_minor:
        return False, "value above the agent's limit"
    if category and agent.categories and category not in agent.categories:
        return False, f"category {category} not enabled for this agent"
    if evaluate_suspension(session, code):
        return False, f"suspended: {agent.suspension_reason}"
    if sod_action:
        conflict = sod_conflict(session, code, sod_action, sod_refs or {})
        if conflict:
            return False, conflict
    return True, None


def sod_conflict(session: Session, code: str, action: str, refs: dict) -> Optional[str]:
    """Segregation of duties for an action an agent is about to take: the rules of ``sod_rule`` are evaluated for the agent's own
    history and for the person the agent acts for (the session's principal), so an agent cannot be used to do what that person
    could not do. The attempt is recorded as a SoD violation. Returns the reason or None."""
    actors = [(agent_actor_id(session, code), f"agent {code}")]
    human = session.info.get("principal")
    if human is not None and not getattr(human, "agent_code", None) and human.user_id != uuid.UUID(int=0):
        actors.append((human.user_id, "the requesting user"))
    for actor_id, who in actors:
        for rule in sod.conflicts(session, action, refs, actor_id):
            sod._log_violation(current_tenant(session), rule, actor_id, action, refs, "BLOCKED")
            return f"segregation of duties {rule.code} for {who}: {rule.description}"
    return None


def record_action(session: Session, code: str, action: str, refs: dict) -> None:
    """Log an action an agent took for the segregation-of-duties history (is_agent)."""
    session.add(ActionLog(tenant_id=current_tenant(session), actor_id=agent_actor_id(session, code), action=action,
                          refs={k: str(v) for k, v in refs.items() if v is not None}, is_agent=True, created_by=current_user(session)))
    session.flush()


def permit(session: Session, code: str, *, object_type: str, object_id: uuid.UUID, object_ref: str, required_level: str = "L1",
           scope: Optional[str] = None, value_minor: Optional[int] = None, category: Optional[str] = None, sod_action: Optional[str] = None,
           sod_refs: Optional[dict] = None, inputs: Optional[dict] = None, log_denial: bool = True) -> bool:
    """The check every call site makes before an agent acts. A refusal is logged as a DENIED run (with the reason) so the agent
    console shows what was held back. ``sod_action``/``sod_refs`` declare the segregation-of-duties action the agent takes (checked
    for the agent and for the person it acts for); a site whose action must count in the SoD history calls ``record_action``."""
    allowed, reason = guard(session, code, required_level=required_level, scope=scope, value_minor=value_minor, category=category,
                            sod_action=sod_action, sod_refs=sod_refs)
    if not allowed and log_denial:
        log_run(session, code, object_type=object_type, object_id=object_id, object_ref=object_ref, inputs=inputs or {}, evidence=[],
                output={}, confidence=None, action_taken="DENIED", denial_reason=reason)
    return allowed


def log_run(session: Session, code: str, *, object_type: str, object_id: uuid.UUID, object_ref: str, inputs: dict,
            evidence: list, output: dict, confidence: Optional[float], action_taken: str,
            denial_reason: Optional[str] = None) -> str:
    agent = get(session, code)
    run = AgentRun(
        tenant_id=current_tenant(session), agent_code=code, object_type=object_type, object_id=object_id,
        object_ref=object_ref, inputs=inputs, evidence=evidence, model_version=agent.model_version, output=output,
        confidence=confidence, autonomy_level=agent.autonomy_level, action_taken=action_taken,
        denial_reason=denial_reason, created_by=current_user(session),
    )
    session.add(run)
    session.flush()
    return f"agent-run:{run.id}"


def feedback(session: Session, run_ref: Optional[str], outcome: str) -> None:
    """Human feedback on a run (ACCEPTED | REJECTED); it drives the acceptance rate and automatic suspension."""
    if not run_ref or not run_ref.startswith("agent-run:"):
        return
    run = session.get(AgentRun, uuid.UUID(run_ref.split(":", 1)[1]))
    if run is not None:
        run.human_feedback = outcome
        session.flush()
        evaluate_suspension(session, run.agent_code)


def feedback_count(session: Session, code: str) -> int:
    return session.execute(select(func.count()).select_from(AgentRun).where(AgentRun.agent_code == code,
                                                                          AgentRun.human_feedback.is_not(None))).scalar_one()


def recommend(session: Session, code: str, *, object_type: str, object_id: uuid.UUID, object_ref: str, dedup_key: str, title: str,
              rationale: str, proposal: dict, candidate_role: str, deep_link: Optional[str] = None,
              value_at_risk_minor: Optional[int] = None, evidence: Optional[list] = None, confidence: Optional[float] = None):
    """L1/L2 output: a recommendation for a human. Returns None when the agent is off or the same advice is already open."""
    from app.pic.models import Recommendation
    allowed, reason = guard(session, code, required_level="L1")
    if not allowed:
        log_run(session, code, object_type=object_type, object_id=object_id, object_ref=object_ref, inputs={"dedup": dedup_key},
                evidence=evidence or [], output={}, confidence=confidence, action_taken="DENIED", denial_reason=reason)
        return None
    existing = session.execute(select(Recommendation).where(Recommendation.agent_code == code, Recommendation.dedup_key == dedup_key,
                                                            Recommendation.status == "OPEN")).scalar_one_or_none()
    if existing is not None:
        return existing
    ref = log_run(session, code, object_type=object_type, object_id=object_id, object_ref=object_ref, inputs={"dedup": dedup_key},
                  evidence=evidence or [], output={"title": title, "proposal": proposal}, confidence=confidence,
                  action_taken="RECOMMENDED" if LEVELS[get(session, code).autonomy_level] < 2 else "DRAFTED")
    rec = Recommendation(tenant_id=current_tenant(session), agent_code=code, agent_run_id=uuid.UUID(ref.split(":", 1)[1]), dedup_key=dedup_key,
                         object_type=object_type, object_id=object_id, object_ref=object_ref, title=title, rationale=rationale,
                         proposal=proposal, deep_link=deep_link, value_at_risk_minor=value_at_risk_minor, candidate_role=candidate_role,
                         created_by=current_user(session))
    session.add(rec)
    session.flush()
    return rec
