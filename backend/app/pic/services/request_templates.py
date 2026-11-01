"""Request templates for services, IT, marketing and facilities (BP M04 "free-text and service requests with templates").

Rule ``REQUEST-TEMPLATES`` is the tenant's template catalogue; each template carries

    name, group, guidance          what the requester sees in the picker
    line                           defaults for the requisition line (item_type, purchase_type, material_group, category, uom)
    defaultAccountType             the account assignment type the form pre-selects (the code is the requester's cost object)
    requiredFields                 line fields that must be filled before the requisition is submitted
    quotePolicy                    minQuotes from minQuotesFromMinor (tightens the value-based quote policy); sourcingEventAboveMinor
                                   (from this value a sourcing event can replace the quotes)
    approverHints                  shown with the requisition and kept in its policy hints

A requisition line names its template with ``template``; the choice is kept on the line (``source_determination.template``)."""
from typing import Optional

from sqlalchemy.orm import Session

from app.pic.platform.errors import Problem, rule_violation
from app.pic.services import mandatory, p2p_rules

KEY = "REQUEST-TEMPLATES"
LINE_DEFAULTS = ("item_type", "purchase_type", "material_group", "category", "uom")


def _rule(session: Session):
    return p2p_rules.rule(session, KEY)


def catalogue(session: Session) -> dict[str, dict]:
    return dict((_rule(session).body.get("templates") or {}))


def get(session: Session, code: str) -> dict:
    templates = catalogue(session)
    template = templates.get(str(code or "").upper()) or templates.get(code)
    if template is None:
        raise Problem(422, "UNKNOWN_TEMPLATE", f"Request template {code} does not exist; known: {', '.join(sorted(templates)) or 'none'}",
                      rule_ref=KEY)
    return template


def apply(session: Session, code: str, data: dict) -> dict:
    """The line data with the template's defaults filled in (never overwriting what the requester entered)."""
    template = get(session, code)
    out = dict(data)
    for key, value in (template.get("line") or {}).items():
        if out.get(key) in (None, ""):
            out[key] = value
    if template.get("defaultAccountType") and not out.get("account_assignment_type") and out.get("account_assignment_code"):
        out["account_assignment_type"] = template["defaultAccountType"]
    out["template"] = str(code)
    return out


def missing(template: dict, line) -> list[str]:
    """Required template fields a PrLine does not have."""
    return [f for f in template.get("requiredFields") or [] if mandatory.blank(getattr(line, f, None))]


def code_of(line) -> Optional[str]:
    return ((getattr(line, "source_determination", None) or {}).get("template")) or None


def quote_requirement(template: Optional[dict], value_minor: int, base_required: int) -> tuple[int, Optional[int]]:
    """(quotes required, value from which a sourcing event replaces the quotes) for a template line: the template can only tighten
    the value-based policy of rule QUOTE-POLICY, never relax it."""
    if not template:
        return base_required, None
    policy = template.get("quotePolicy") or {}
    required = base_required
    if policy.get("minQuotes") and value_minor >= int(policy.get("minQuotesFromMinor", 0)):
        required = max(required, int(policy["minQuotes"]))
    sourcing = int(policy["sourcingEventAboveMinor"]) if policy.get("sourcingEventAboveMinor") else None
    return required, sourcing


def listing(session: Session, principal) -> list[dict]:
    """The picker: every template with the cost objects of the requester that fit its default account type."""
    owned = list(principal.attr("cost_objects") or [])
    out = []
    for code, t in catalogue(session).items():
        default_type = t.get("defaultAccountType")
        suggestion = next((c.split(":", 1)[1] for c in owned if default_type and c.startswith(f"{default_type}:")), None)
        out.append({"code": code, "name": t.get("name", code), "group": t.get("group"), "guidance": t.get("guidance"),
                    "line": t.get("line") or {}, "defaultAccountType": default_type, "defaultAccountCode": suggestion,
                    "requiredFields": t.get("requiredFields") or [], "quotePolicy": t.get("quotePolicy") or {},
                    "approverHints": t.get("approverHints") or []})
    return sorted(out, key=lambda r: (r["group"] or "", r["code"]))


def validate_body(body: dict) -> None:
    """Structural check of an edited REQUEST-TEMPLATES body (used by tests and the admin tooling)."""
    for code, t in (body.get("templates") or {}).items():
        unknown = [f for f in t.get("requiredFields") or [] if f not in mandatory.CATALOGUE["REQUISITION"]["lines"]]
        if unknown:
            raise rule_violation(f"Template {code}: unknown required field(s) {', '.join(unknown)}", KEY)
