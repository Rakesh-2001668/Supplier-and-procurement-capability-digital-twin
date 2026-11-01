"""Guided Buying Agent (AG-03, autonomy L2: it drafts, the requester decides; blueprint §25, workflow F2).

Invoked from two places, always through ``agents.permit`` (tenant AI switch, kill switch, autonomy, drift suspension) and always
logged as an agent run:

- the guided-buying search (``GET /v1/guided-buying/search``): the agent adds its reading of the result -- the best contract,
  catalogue or material match, and an account assignment drafted from the requester's own earlier requisitions (else their cost
  object) -- to the response under ``agent``, with the run reference ``aiRef``;
- requisition creation (``requisition.create``): free-text lines are searched again; when a contract or catalogue item exists the
  suggestion is stored on the line (``source_determination.guidedBuying``), audited and logged. A line that arrives with the
  ``guided_run`` of a search the requester used is the human feedback: it is ACCEPTED when the requester took the recommended
  channel and REJECTED otherwise, which feeds the acceptance rate and the automatic suspension (agents.feedback).
"""
import uuid
from collections import Counter
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import AgentRun, PrLine
from app.pic.platform import agents, audit
from app.pic.services.common import principal

CODE = "GUIDED_BUYING"
MAX_REVIEWED_LINES = 5


def _best(result: dict) -> Optional[dict]:
    channel = result.get("recommendedChannel")
    hits = (result.get("results") or {}).get(str(channel).lower()) or []
    return hits[0] if hits and channel != "FREE_TEXT" else None


def _account_assignment(session: Session, material_group: Optional[str]) -> Optional[dict]:
    """The requester's usual account assignment for this material group, else their first cost object."""
    p = principal(session)
    query = select(PrLine.account_assignment_type, PrLine.account_assignment_code).where(
        PrLine.created_by == p.user_id, PrLine.account_assignment_code.is_not(None))
    if material_group:
        query = query.where(PrLine.material_group == material_group)
    rows = session.execute(query.order_by(PrLine.created_at.desc()).limit(50)).all()
    if rows:
        (kind, code), count = Counter((k, c) for k, c in rows).most_common(1)[0]
        return {"type": kind, "code": code, "basis": f"used on {count} of your last {len(rows)} lines for this material group"}
    owned = p.attr("cost_objects") or []
    if owned:
        kind, _, code = str(owned[0]).partition(":")
        return {"type": kind or "COST_CENTER", "code": code or str(owned[0]), "basis": "your cost object"}
    return None


def assist_search(session: Session, query: str, plant: Optional[str], result: dict) -> Optional[dict]:
    """The agent's reading of a guided-buying search; None when the agent may not act (or the tenant has no such agent)."""
    if not agents.exists(session, CODE):
        return None
    p = principal(session)
    object_id = uuid.uuid5(uuid.NAMESPACE_URL, f"guided-search:{p.tenant_id}:{p.user_id}:{query.strip().lower()}:{plant or ''}")
    if not agents.permit(session, CODE, object_type="GUIDED_SEARCH", object_id=object_id, object_ref=query.strip()[:60], required_level="L1",
                         inputs={"query": query, "plant": plant}, log_denial=False):
        return None
    hit = _best(result)
    group = (hit or {}).get("materialGroup")
    assignment = _account_assignment(session, group)
    suggestion = None
    if hit:
        suggestion = {k: hit.get(k) for k in ("channel", "contract", "line", "contractLineId", "id", "supplierPartNo", "material", "description",
                                              "unitPriceMinor", "uom", "score") if hit.get(k) is not None}
    channel = result.get("recommendedChannel")
    note = (f"Use the {str(channel).lower()} item before free text (P03)" if hit else "Nothing in contracts, catalogues or the material master matches; free text is allowed")
    ref = agents.log_run(session, CODE, object_type="GUIDED_SEARCH", object_id=object_id, object_ref=query.strip()[:60],
                         inputs={"query": query, "plant": plant}, evidence=[f"{n}:{len(h)}" for n, h in (result.get("results") or {}).items()],
                         output={"channel": channel, "suggestion": suggestion, "accountAssignment": assignment},
                         confidence=float(hit["score"]) if hit and hit.get("score") is not None else 0.5,
                         action_taken="DRAFTED" if agents.LEVELS[agents.get(session, CODE).autonomy_level] >= 2 else "RECOMMENDED")
    return {"agent": CODE, "aiRef": ref, "channel": channel, "suggestion": suggestion, "accountAssignment": assignment, "note": note}


def on_create(session: Session, pr, lines_in: list[dict], lines: list[PrLine]) -> None:
    """Called by requisition.create with the request lines and the lines built from them (same order)."""
    if not agents.exists(session, CODE) or principal(session).is_agent or pr.origin == "MRP":
        return
    from app.pic.services import requisition  # local import: requisition imports this module's callers
    reviewed = 0
    for data, line in zip(lines_in, lines):
        run_ref = data.get("guided_run")
        if run_ref:
            _feedback(session, run_ref, line)
            continue
        if line.item_type != "FREE_TEXT" or reviewed >= MAX_REVIEWED_LINES:
            continue
        reviewed += 1
        result = requisition.search(session, line.description, line.plant)
        hit = _best(result)
        if hit is None:
            continue
        if not agents.permit(session, CODE, object_type="REQUISITION", object_id=pr.id, object_ref=pr.number, required_level="L2",
                             inputs={"line": line.line_no, "description": line.description}, log_denial=False):
            return
        suggestion = {k: hit.get(k) for k in ("channel", "contract", "line", "contractLineId", "id", "supplierPartNo", "material", "description",
                                              "unitPriceMinor", "uom", "score") if hit.get(k) is not None}
        ref = agents.log_run(session, CODE, object_type="REQUISITION", object_id=pr.id, object_ref=pr.number,
                             inputs={"line": line.line_no, "description": line.description}, evidence=[str(hit.get("description"))],
                             output={"channel": result["recommendedChannel"], "suggestion": suggestion}, confidence=float(hit.get("score") or 0),
                             action_taken="DRAFTED")
        line.source_determination = {**(line.source_determination or {}), "guidedBuying": {"run": ref, "suggestion": suggestion}}
        audit.record(session, "REQUISITION", pr.id, "GUIDED_BUYING_SUGGESTED", object_ref=pr.number, ai_ref=ref,
                     after={"line": line.line_no, "channel": result["recommendedChannel"], "suggestion": suggestion},
                     reason="a contract or catalogue item matches this free-text line (P03)")


def _feedback(session: Session, run_ref: str, line: PrLine) -> None:
    """The requester's line is the human feedback on the search run: the recommended channel taken = ACCEPTED."""
    try:
        run = session.get(AgentRun, uuid.UUID(run_ref.split(":", 1)[1])) if run_ref.startswith("agent-run:") else None
    except ValueError:
        run = None
    if run is None or run.agent_code != CODE or run.human_feedback is not None:
        return
    channel = (run.output or {}).get("channel")
    outcome = "ACCEPTED" if channel and line.item_type == channel else "REJECTED"
    line.source_determination = {**(line.source_determination or {}), "guidedBuying": {"run": run_ref, "outcome": outcome, "recommended": channel}}
    agents.feedback(session, run_ref, outcome)
