"""Industry template packs (blueprint section 23): preview and apply.

A template contributes rule-set bodies (``ruleOverrides`` on top of the default pack in seed/reference.RULE_SETS). Applying a
template never edits a rule version (P14): a rule set that is missing is added, and one whose body differs from the template's
becomes a new effective-dated version (``<current>+<template>.<n>``, effective today). Rules the tenant already customised away from
the *previous* template's body are left alone and reported; rules of the previous template that the new one does not set return to
the default pack body only if they still equal the previous template's body. Applying the template the tenant already runs, with
every rule in place, changes nothing and records nothing (idempotent). Each real application is recorded (who, when, what changed)
and audited.
"""
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import RuleSet, TemplateApplication, Tenant
from app.pic.platform import audit, clock
from app.pic.platform.errors import Problem
from app.pic.seed import reference, templates
from app.pic.seed.templates import TEMPLATES
from app.pic.services.common import principal

SKIP_KEYS = {"MFA"}  # tenant security posture, not an industry setting


def _admin(session: Session) -> None:
    if "TENANT_ADMIN" not in principal(session).roles:
        raise Problem(403, "FORBIDDEN", "Requires the tenant administrator", rule_ref="RBAC")


def _current_rules(session: Session) -> dict:
    """The tenant-wide (unscoped) rule set in force today per key: what ``rules.resolve`` returns without scope."""
    today = clock.today()
    current: dict = {}
    never = clock.now().replace(year=1970)
    for rs in session.execute(select(RuleSet).where(RuleSet.company_code.is_(None), RuleSet.plant.is_(None), RuleSet.category.is_(None),
                                                    RuleSet.purchase_type.is_(None), RuleSet.supplier_group.is_(None),
                                                    RuleSet.effective_from <= today)).scalars():
        if rs.effective_to is not None and rs.effective_to < today:
            continue
        best = current.get(rs.key)
        if best is None or (rs.effective_from, rs.created_at or never, rs.version) > (best.effective_from, best.created_at or never, best.version):
            current[rs.key] = rs
    return current


def _diff(old: dict, new: dict) -> list[dict]:
    return [{"field": k, "from": old.get(k), "to": new.get(k)} for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]


def _plan(session: Session, code: str) -> dict:
    if code not in TEMPLATES:
        raise Problem(404, "NOT_FOUND", f"Industry template {code} not found")
    tenant = session.get(Tenant, principal(session).tenant_id)
    previous = tenant.industry_template
    wanted = templates.merged_rules(reference.RULE_SETS, code)
    prior = templates.merged_rules(reference.RULE_SETS, previous) if previous in TEMPLATES else {}
    current = _current_rules(session)
    changes, unchanged, skipped = [], [], []
    for key, (body, description) in wanted.items():
        if key in SKIP_KEYS:
            continue
        have = current.get(key)
        in_template = key in TEMPLATES[code]["ruleOverrides"]
        was_template = previous != code and key in TEMPLATES.get(previous, {}).get("ruleOverrides", {})
        if have is None:
            changes.append({"key": key, "action": "ADD", "fromVersion": None, "fields": [{"field": f, "from": None, "to": v} for f, v in body.items()],
                            "description": description})
        elif in_template and have.body != body:
            base_was = prior.get(key, (None,))[0]
            if previous != code and base_was is not None and have.body != base_was and key in TEMPLATES.get(previous, {}).get("ruleOverrides", {}):
                skipped.append({"key": key, "version": have.version, "reason": "customised after the previous template was applied; left as is"})
            else:
                changes.append({"key": key, "action": "CHANGE", "fromVersion": have.version, "fields": _diff(have.body, body), "description": description})
        elif was_template and not in_template:
            default_body = reference.RULE_SETS[key][0] if key in reference.RULE_SETS else None
            if default_body is None:
                continue
            if have.body == prior[key][0]:
                if have.body != default_body:
                    changes.append({"key": key, "action": "REVERT", "fromVersion": have.version, "fields": _diff(have.body, default_body),
                                    "description": f"{TEMPLATES[previous]['name']} setting not used by {TEMPLATES[code]['name']}"})
            else:
                skipped.append({"key": key, "version": have.version, "reason": "customised after the previous template was applied; left as is"})
        else:
            unchanged.append(key)
    return {"tenant": tenant, "previous": previous, "changes": changes, "unchanged": sorted(unchanged), "skipped": skipped, "wanted": wanted,
            "prior": prior, "current": current}


def preview(session: Session, code: str) -> dict:
    plan = _plan(session, code)
    t = TEMPLATES[code]
    return {"template": code, "name": t["name"], "current": plan["previous"], "alreadyApplied": plan["previous"] == code,
            "switchesTemplate": plan["previous"] != code, "ruleSetChanges": plan["changes"], "unchangedRuleSets": plan["unchanged"],
            "customisedLeftAlone": plan["skipped"], "noop": plan["previous"] == code and not plan["changes"],
            "willAdd": sum(c["action"] == "ADD" for c in plan["changes"]), "willChange": sum(c["action"] in ("CHANGE", "REVERT") for c in plan["changes"]),
            "history": history(session)}


def history(session: Session) -> list[dict]:
    return [{"template": a.template, "previousTemplate": a.previous_template, "appliedBy": str(a.applied_by) if a.applied_by else None,
             "appliedAt": a.applied_at.isoformat(), "changes": a.changes}
            for a in session.execute(select(TemplateApplication).order_by(TemplateApplication.applied_at.desc()).limit(20)).scalars()]


def _next_version(session: Session, key: str, base: str, code: str) -> str:
    have = set(session.execute(select(RuleSet.version).where(RuleSet.key == key)).scalars())
    n = 1
    while f"{base}+{code.lower()}.{n}" in have:
        n += 1
    return f"{base}+{code.lower()}.{n}"


def apply(session: Session, code: str) -> dict:
    _admin(session)
    plan = _plan(session, code)
    tenant, previous = plan["tenant"], plan["previous"]
    if previous == code and not plan["changes"]:
        return {"applied": False, "noop": True, "template": code, "message": f"{TEMPLATES[code]['name']} is already applied; nothing changed",
                "ruleSetChanges": [], "customisedLeftAlone": plan["skipped"]}
    today = clock.today()
    done = []
    for c in plan["changes"]:
        key = c["key"]
        have = plan["current"].get(key)
        if c["action"] == "ADD":
            body, description = plan["wanted"][key]
            session.add(RuleSet(tenant_id=tenant.id, key=key, version=reference.RULES_VERSION, effective_from=reference.RULES_FROM, body=body,
                                description=description, created_by=principal(session).user_id))
            done.append({"key": key, "action": "ADD", "version": reference.RULES_VERSION})
            continue
        body = plan["wanted"][key][0] if c["action"] == "CHANGE" else reference.RULE_SETS[key][0]
        version = _next_version(session, key, have.version.split("+")[0], code)
        session.add(RuleSet(tenant_id=tenant.id, key=key, version=version, effective_from=max(today, have.effective_from), body=body,
                            description=f"{c['description']} (template {code})"[:400], created_by=principal(session).user_id))
        done.append({"key": key, "action": c["action"], "fromVersion": have.version, "version": version})
    tenant.industry_template = code
    applied = TemplateApplication(tenant_id=tenant.id, template=code, previous_template=previous, applied_by=principal(session).user_id,
                                  applied_at=clock.now(), changes={"ruleSets": done, "customisedLeftAlone": plan["skipped"]},
                                  created_by=principal(session).user_id)
    session.add(applied)
    session.flush()
    audit.record(session, "TENANT", tenant.id, "TEMPLATE_APPLIED", object_ref=code, before={"template": previous},
                 after={"template": code, "ruleSets": done, "customisedLeftAlone": plan["skipped"]})
    return {"applied": True, "noop": False, "template": code, "previousTemplate": previous, "ruleSetChanges": done,
            "customisedLeftAlone": plan["skipped"], "appliedAt": applied.applied_at.isoformat()}
