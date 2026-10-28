"""Agent registry, autonomy guard and run log (§13.2, blueprint §25).

Agents act under a role, are limited by autonomy level, value and category,
and can be switched off per agent. Every run is stored with its inputs,
evidence, model version, output, confidence and the action taken.
"""
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, current_user
from app.pic.models import Agent, AgentRun
from app.pic.platform.auth import ROLE_SCOPES

LEVELS = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4}

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


def acceptance_rate(session: Session, code: str) -> Optional[Decimal]:
    rows = session.execute(
        select(AgentRun.human_feedback, func.count()).where(AgentRun.agent_code == code, AgentRun.human_feedback.is_not(None))
        .group_by(AgentRun.human_feedback)
    ).all()
    total = sum(n for _, n in rows)
    if total < 20:
        return None
    accepted = sum(n for fb, n in rows if fb == "ACCEPTED")
    return Decimal(accepted) / Decimal(total)


def guard(session: Session, code: str, *, required_level: str, scope: Optional[str] = None,
          value_minor: Optional[int] = None, category: Optional[str] = None) -> tuple[bool, Optional[str]]:
    agent = get(session, code)
    if agent.kill_switch:
        return False, "kill switch is on"
    if LEVELS[agent.autonomy_level] < LEVELS[required_level]:
        return False, f"autonomy {agent.autonomy_level} is below required {required_level}"
    if scope and scope not in ROLE_SCOPES.get(agent.run_as_role, set()):
        return False, f"role {agent.run_as_role} lacks scope {scope}"
    if value_minor is not None and agent.value_limit_minor is not None and value_minor > agent.value_limit_minor:
        return False, "value above the agent's limit"
    if category and agent.categories and category not in agent.categories:
        return False, f"category {category} not enabled for this agent"
    rate = acceptance_rate(session, code)
    if rate is not None and rate < Decimal(str(agent.min_acceptance_rate)):
        agent.kill_switch = True
        return False, f"suspended: acceptance rate {rate:.2f} below {agent.min_acceptance_rate}"
    return True, None


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
