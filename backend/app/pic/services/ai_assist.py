"""Gateway-assisted suggestions that sit beside deterministic logic (TD §13): the spend classification second opinion and the
contract redline suggestion with playbook retrieval. Both validate the model output and fall back to a deterministic suggestion;
neither writes business data (a human applies the suggestion through the normal redline / classification review actions)."""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import Clause, Contract
from app.pic.platform import rules
from app.pic.platform.errors import Problem
from app.pic.services import llm_gateway, ml_core

POSITIONS = ("STANDARD", "FALLBACK", "NON_STANDARD")


# ---------------------------------------------------------------- spend classification second opinion
def classification_second_opinion(session: Session, description: str, nodes: list) -> Optional[dict]:
    """The model's choice among the level-3 taxonomy categories for a free-text spend line, or None."""
    if not llm_gateway.configured() or not (description or "").strip():
        return None
    categories = {n.code: n.name for n in nodes if getattr(n, "level", 3) == 3}
    if not categories:
        return None

    def validate(text: str) -> dict:
        data = llm_gateway.json_object(text, {"category": str})
        if data["category"] not in categories:
            raise ValueError("category is not in the taxonomy")
        return data

    listing = "\n".join(f"{code}: {name}" for code, name in sorted(categories.items()))
    result = llm_gateway.chat(
        session, "SPEND_CLASSIFY", [
            {"role": "system", "content": "Classify the purchase description into exactly one category code from the list. "
                                          "Reply as JSON: {\"category\": \"<code>\"}."},
            {"role": "user", "content": f"CATEGORIES:\n{listing}\n\nDESCRIPTION: {description[:300]}"}],
        validator=validate, json_mode=True, max_tokens=60)
    if not result.ok:
        return None
    return {"category": result.data["category"], "score": 0, "evidence": ["LLM second opinion"], "source": "LLM", "model": result.model}


# ---------------------------------------------------------------- contract redline suggestion
def _playbook_candidates(session: Session, contract: Contract, clause: Clause, k: int = 3) -> list[dict]:
    """Retrieve the playbook clause texts most similar to the clause in question (hashing-embedding cosine) from the template of
    the contract type, plus the playbook fallback position for the clause code."""
    playbook = rules.resolve(session, "CLM-PLAYBOOK").body
    templates = playbook.get("templates", {}).get(getattr(contract, "type", None) or "", []) or \
        [t for group in playbook.get("templates", {}).values() for t in group]
    query = ml_core.hash_vector(f"{clause.code} {clause.title if hasattr(clause, 'title') else ''} {clause.text or ''}")
    scored = sorted(({"code": t["code"], "title": t.get("title"), "text": t["text"],
                      "similarity": round(ml_core.cosine(query, ml_core.hash_vector(f"{t['code']} {t.get('title') or ''} {t['text']}")), 4)}
                     for t in templates), key=lambda x: (-x["similarity"], x["code"]))
    same = [t for t in scored if t["code"] == clause.code]
    others = [t for t in scored if t["code"] != clause.code]
    return (same + others)[:k]


def suggest_redline(session: Session, contract: Contract, clause_code: str, proposed_text: Optional[str] = None) -> dict:
    """A buyer-side suggestion for a clause: retrieval of the playbook texts, then (gateway configured) a model-drafted counter text
    validated to JSON {suggestedText, position, rationale}; otherwise the deterministic suggestion = the playbook's standard text
    (STANDARD) or, where the playbook has a fallback for the clause, the fallback wording (FALLBACK)."""
    clause = session.execute(select(Clause).where(Clause.contract_id == contract.id, Clause.code == clause_code)).scalar_one_or_none()
    if clause is None:
        raise Problem(404, "NOT_FOUND", f"Clause {clause_code} not found in {contract.number}")
    playbook = rules.resolve(session, "CLM-PLAYBOOK")
    candidates = _playbook_candidates(session, contract, clause)
    standard = next((c for c in candidates if c["code"] == clause.code), candidates[0] if candidates else None)
    fallback = (playbook.body.get("fallbacks") or {}).get(clause.code)
    current = (proposed_text or clause.text or "").strip()
    deterministic = {
        "suggestedText": (standard or {}).get("text") or clause.text, "position": "STANDARD",
        "rationale": f"Restore the playbook standard wording for {clause.code}." if standard else "No playbook text found for this clause.",
        "fallbackPosition": fallback,
    }
    if fallback:
        deterministic["alternative"] = {"suggestedText": fallback, "position": "FALLBACK",
                                        "rationale": f"The playbook allows the fallback position: {fallback}."}
    out = {"clause": clause.code, "contract": contract.number, "current": current, "source": "PLAYBOOK_RULES", "playbook": playbook.ref,
           "retrieved": [{k: c[k] for k in ("code", "title", "similarity")} for c in candidates], **deterministic}
    if not llm_gateway.configured() or not candidates:
        return out

    def validate(text: str) -> dict:
        data = llm_gateway.json_object(text, {"suggestedText": str, "position": str, "rationale": str})
        if data["position"] not in POSITIONS:
            raise ValueError("position is not a playbook position")
        if len(data["suggestedText"]) > 2000:
            raise ValueError("suggested text is too long")
        return data

    context = "\n".join(f"- {c['code']} ({c['title']}): {c['text']}" for c in candidates)
    result = llm_gateway.chat(
        session, "REDLINE", [
            {"role": "system", "content": "You help a contract manager respond to a clause change. Using only the PLAYBOOK clauses, propose "
                                          "counter wording that stays within the playbook. Reply as JSON: "
                                          "{\"suggestedText\": \"...\", \"position\": \"STANDARD|FALLBACK|NON_STANDARD\", \"rationale\": \"...\"}."},
            {"role": "user", "content": f"PLAYBOOK:\n{context}\nFALLBACK POSITION: {fallback or 'none'}\nCLAUSE {clause.code} CURRENT/PROPOSED TEXT: {current[:1500]}"}],
        validator=validate, json_mode=True, max_tokens=500)
    if result.ok:
        out.update(source="GATEWAY", model=result.model, suggestedText=result.data["suggestedText"].strip(), position=result.data["position"],
                   rationale=result.data["rationale"].strip(), deterministic=deterministic)
    else:
        out["gatewayFallback"] = result.reason
    return out
