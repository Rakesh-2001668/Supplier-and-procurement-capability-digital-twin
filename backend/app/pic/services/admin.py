"""M13 administration: organisation setup (ADM-01), currencies and FX, users and roles (ADM-04), industry templates
and the agent console commands (AIX-03: autonomy, on-demand runs, recommendations)."""
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import (
    Agent, AgentRun, AppUser, CompanyCode, CostObject, Currency, FxRate, Plant, Recommendation, RuleSet, StorageLocation, Tenant,
)
from app.pic.platform import agents, audit, clock, rules
from app.pic.platform.auth import ROLE_SCOPES
from app.pic.platform.errors import Problem, not_found
from app.pic.seed.templates import TEMPLATES
from app.pic.services.common import principal

SENSITIVE_ROLES = {"TENANT_ADMIN", "FINANCE_CONTROLLER", "CPO"}
# Role pairs one person must not hold together (blueprint §4.1, enforced at assignment as well as at command time).
TOXIC_PAIRS = [({"SUPPLIER_MANAGER"}, {"FINANCE_CONTROLLER"}, "SOD-02: bank changes and payment approval"),
               ({"BUYER"}, {"RECEIVER"}, "SOD-03: PO creation and goods receipt"),
               ({"BUYER"}, {"AP_CLERK"}, "SOD-04: PO creation and invoice exceptions")]


def _admin(session: Session) -> None:
    if "TENANT_ADMIN" not in principal(session).roles:
        raise Problem(403, "FORBIDDEN", "Requires the tenant administrator", rule_ref="RBAC")


# ---------------------------------------------------------------- ADM-01 organisation, calendars, currencies
def organisation(session: Session) -> dict:
    tenant = session.get(Tenant, principal(session).tenant_id)
    template = TEMPLATES.get(tenant.industry_template, {})
    return {
        "tenant": {"code": tenant.code, "name": tenant.name, "industryTemplate": tenant.industry_template, "templateName": template.get("name"),
                   "baseCurrency": tenant.base_currency, "timezone": tenant.timezone},
        "companyCodes": [{"code": c.code, "name": c.name, "gstin": c.gstin, "currency": c.currency, "fiscalYearStartMonth": c.fiscal_year_start_month}
                         for c in session.execute(select(CompanyCode).order_by(CompanyCode.code)).scalars()],
        "plants": [{"code": p.code, "name": p.name, "companyCode": p.company_code, "stateCode": p.state_code, "workingDays": p.working_days,
                    "holidays": [h.isoformat() for h in (p.holidays or [])],
                    "storageLocations": [{"code": s.code, "name": s.name} for s in session.execute(
                        select(StorageLocation).where(StorageLocation.plant == p.code).order_by(StorageLocation.code)).scalars()]}
                   for p in session.execute(select(Plant).order_by(Plant.code)).scalars()],
        "costObjects": [{"type": c.type, "code": c.code, "name": c.name, "companyCode": c.company_code}
                        for c in session.execute(select(CostObject).order_by(CostObject.type, CostObject.code)).scalars()],
        "currencies": [{"code": c.code, "name": c.name, "decimals": c.decimals, "active": c.active}
                       for c in session.execute(select(Currency).order_by(Currency.code)).scalars()],
        "fxRates": [{"from": r.from_ccy, "to": r.to_ccy, "rate": str(r.rate), "validFrom": r.valid_from.isoformat(), "source": r.source}
                    for r in session.execute(select(FxRate).order_by(FxRate.from_ccy, FxRate.valid_from.desc())).scalars()],
    }


def add_fx_rate(session: Session, from_ccy: str, to_ccy: str, rate: Decimal, valid_from: date, source: str) -> FxRate:
    _admin(session)
    if rate <= 0:
        raise Problem(422, "INVALID_RATE", "FX rate must be positive")
    known = set(session.execute(select(Currency.code)).scalars())
    if from_ccy not in known or to_ccy not in known:
        raise Problem(422, "UNKNOWN_CURRENCY", f"Activate {from_ccy} and {to_ccy} first")
    existing = session.execute(select(FxRate).where(FxRate.from_ccy == from_ccy, FxRate.to_ccy == to_ccy, FxRate.valid_from == valid_from)).scalar_one_or_none()
    if existing:
        raise Problem(409, "RATE_EXISTS", f"A {from_ccy}/{to_ccy} rate already exists from {valid_from}; add a later-dated rate instead (P14)")
    fx = FxRate(tenant_id=principal(session).tenant_id, from_ccy=from_ccy, to_ccy=to_ccy, rate=rate, valid_from=valid_from, source=source,
                created_by=principal(session).user_id)
    session.add(fx)
    session.flush()
    audit.record(session, "FX_RATE", fx.id, "CREATED", object_ref=f"{from_ccy}/{to_ccy}", after={"rate": str(rate), "validFrom": valid_from.isoformat()})
    return fx


def convert(session: Session, amount_minor: int, from_ccy: str, to_ccy: str, on: Optional[date] = None) -> tuple[int, Optional[str]]:
    """Group-currency normalisation for the spend cube: latest rate valid on the date (direct or inverse)."""
    if from_ccy == to_ccy:
        return amount_minor, None
    on = on or clock.today()
    for a, b, invert in ((from_ccy, to_ccy, False), (to_ccy, from_ccy, True)):
        fx = session.execute(select(FxRate).where(FxRate.from_ccy == a, FxRate.to_ccy == b, FxRate.valid_from <= on)
                             .order_by(FxRate.valid_from.desc())).scalars().first()
        if fx:
            rate = (Decimal(1) / fx.rate) if invert else fx.rate
            return int((Decimal(amount_minor) * rate).quantize(Decimal("1"), ROUND_HALF_UP)), f"{a}/{b}@{fx.valid_from}"
    raise Problem(422, "FX_RATE_MISSING", f"No {from_ccy}/{to_ccy} rate valid on {on}")


def add_plant_holidays(session: Session, plant_code: str, holidays: list[date], source: str) -> list[date]:
    """ADM-01 factory calendar: add public holidays to a plant (union with the dates already there; nothing is removed,
    so planned dates already computed against the calendar keep their basis). Returns the dates actually added."""
    _admin(session)
    plant = session.execute(select(Plant).where(Plant.code == plant_code)).scalar_one_or_none()
    if plant is None:
        raise not_found("Plant", plant_code)
    if not source or len(source.strip()) < 5:
        raise Problem(422, "SOURCE_REQUIRED", "Name the holiday list (gazette notification / G.O.) the dates come from")
    have = set(plant.holidays or [])
    added = sorted(set(holidays) - have)
    if added:
        plant.holidays = sorted(have | set(added))
        audit.record(session, "PLANT", plant.id, "CALENDAR_UPDATED", object_ref=plant.code, before={"holidays": len(have)},
                     after={"added": [d.isoformat() for d in added], "holidays": len(plant.holidays)}, reason=source)
    return added


# ---------------------------------------------------------------- ADM-04 users and roles
def users(session: Session) -> list[dict]:
    return [{"id": str(u.id), "email": u.email, "name": u.full_name, "roles": u.roles, "active": u.active, "mfaEnrolled": u.mfa_enrolled,
             "supplierUser": u.supplier_id is not None, "attributes": u.attributes}
            for u in session.execute(select(AppUser).order_by(AppUser.supplier_id.is_not(None), AppUser.email)).scalars()]


def assign_roles(session: Session, user: AppUser, roles_: list[str], reason: str) -> AppUser:
    _admin(session)
    p = principal(session)
    unknown = [r for r in roles_ if r not in ROLE_SCOPES]
    if unknown:
        raise Problem(422, "UNKNOWN_ROLE", f"Unknown role(s): {', '.join(unknown)}")
    if user.supplier_id is not None and set(roles_) != {"SUPPLIER_USER"}:
        raise Problem(422, "SUPPLIER_USER_ROLES", "Supplier users can only hold SUPPLIER_USER")
    if user.id == p.user_id and "TENANT_ADMIN" in user.roles and "TENANT_ADMIN" not in roles_:
        raise Problem(409, "SELF_LOCKOUT", "You cannot remove your own administrator role")
    for a, b, rule in TOXIC_PAIRS:
        if a & set(roles_) and b & set(roles_):
            raise Problem(409, "SOD_CONFLICT", f"Role combination not allowed ({rule})", rule_ref=rule.split(":")[0])
    if SENSITIVE_ROLES & set(roles_) and not user.mfa_enrolled:
        raise Problem(409, "MFA_REQUIRED", "Approver, finance and admin roles need MFA enrolment (§14)")
    before = list(user.roles)
    user.roles = sorted(set(roles_))
    audit.record(session, "APP_USER", user.id, "ROLES_CHANGED", object_ref=user.email, before={"roles": before}, after={"roles": user.roles},
                 reason=reason)
    return user


def set_active(session: Session, user: AppUser, active: bool, reason: str) -> AppUser:
    _admin(session)
    if user.id == principal(session).user_id and not active:
        raise Problem(409, "SELF_LOCKOUT", "You cannot deactivate yourself")
    user.active = active
    audit.record(session, "APP_USER", user.id, "ACTIVATED" if active else "DEACTIVATED", object_ref=user.email, reason=reason)
    return user


# ---------------------------------------------------------------- templates
def templates(session: Session) -> dict:
    tenant = session.get(Tenant, principal(session).tenant_id)
    applied = {r.key: r.version for r in session.execute(select(RuleSet)).scalars()}
    return {"current": tenant.industry_template,
            "templates": [{"code": code, **{k: v for k, v in t.items() if k != "ruleOverrides"},
                           "ruleOverrides": sorted(t["ruleOverrides"]), "applied": code == tenant.industry_template} for code, t in TEMPLATES.items()],
            "ruleSets": applied}


# ---------------------------------------------------------------- AIX-03 agent console
def set_autonomy(session: Session, code: str, *, level: str, value_limit_minor: Optional[int], categories: Optional[list[str]],
                 kill_switch: Optional[bool], reason: str) -> Agent:
    p = principal(session)
    if "agents:manage" not in p.scopes:
        raise Problem(403, "FORBIDDEN", "Requires agents:manage", rule_ref="RBAC")
    if level not in agents.LEVELS:
        raise Problem(422, "INVALID_LEVEL", "Autonomy is L0..L4")
    agent = agents.get(session, code)
    if level == "L4" and code not in ("TOUCHLESS_PO",) and not categories:
        raise Problem(409, "RULE_VIOLATION", "L4 needs configured categories (blueprint §25)", rule_ref="AIX")
    if agents.LEVELS[level] >= 3 and value_limit_minor is None and agent.value_limit_minor is None and code in ("TOUCHLESS_PO",):
        raise Problem(409, "RULE_VIOLATION", "L3/L4 on transactional agents needs a value limit", rule_ref="AIX")
    before = {"level": agent.autonomy_level, "limit": agent.value_limit_minor, "categories": agent.categories, "killSwitch": agent.kill_switch}
    agent.autonomy_level = level
    if value_limit_minor is not None:
        agent.value_limit_minor = value_limit_minor
    if categories is not None:
        agent.categories = categories
    if kill_switch is not None:
        agent.kill_switch = kill_switch
    audit.record(session, "AGENT", agent.id, "AUTONOMY_CHANGED", object_ref=code, before=before,
                 after={"level": level, "limit": agent.value_limit_minor, "categories": agent.categories, "killSwitch": agent.kill_switch}, reason=reason)
    return agent


def run_agent(session: Session, code: str) -> dict:
    """On-demand run of an agent that scans data (POST /v1/agents/{code}/runs)."""
    from app.pic.services import forecasting, risk, sourcing_strategy, spend
    p = principal(session)
    runners = {
        "DEMAND_SENSING": ("mrp:run", lambda: {"recommendations": len(forecasting.sense(session))}),
        "SUPPLIER_RISK": ("supplier:manage", lambda: {"signals": len(risk.scan(session))}),
        "SPEND_CLASSIFICATION": ("spend:read", lambda: spend.refresh(session, p.tenant_id)),
        "SOURCING_STRATEGY": ("sourcing:manage", lambda: {"recommendations": len(sourcing_strategy.recommend_all(session))}),
    }
    if code not in runners:
        raise Problem(422, "NOT_RUNNABLE", f"{code} runs on its trigger events; on-demand runs exist for {', '.join(sorted(runners))}")
    scope, fn = runners[code]
    if scope not in p.scopes and "agents:manage" not in p.scopes:
        raise Problem(403, "FORBIDDEN", f"Running {code} requires {scope}")
    agent = agents.get(session, code)
    if agent.kill_switch:
        raise Problem(409, "KILL_SWITCH", f"{code} is switched off")
    result = fn()
    audit.record(session, "AGENT", agent.id, "RUN_REQUESTED", object_ref=code, after=result)
    return {"agent": code, "result": result}


def recommendations(session: Session, status: Optional[str] = "OPEN") -> list[dict]:
    p = principal(session)
    query = select(Recommendation).order_by(Recommendation.created_at.desc())
    if status:
        query = query.where(Recommendation.status == status)
    out = []
    for r in session.execute(query).scalars():
        if not (set(p.roles) & {r.candidate_role, "CPO", "TENANT_ADMIN"}):
            continue
        out.append({"id": str(r.id), "agent": r.agent_code, "objectType": r.object_type, "objectRef": r.object_ref, "title": r.title,
                    "rationale": r.rationale, "proposal": r.proposal, "deepLink": r.deep_link, "valueAtRiskMinor": r.value_at_risk_minor,
                    "role": r.candidate_role, "status": r.status, "createdAt": r.created_at.isoformat(), "feedback": r.feedback_comment})
    return out


def decide_recommendation(session: Session, rec: Recommendation, accepted: bool, comment: Optional[str]) -> Recommendation:
    """A human accepts or rejects. Accepting never executes the action by itself (answer contract: recommend, human decides)."""
    p = principal(session)
    if rec.candidate_role not in p.roles and "CPO" not in p.roles:
        raise Problem(403, "FORBIDDEN", f"This recommendation is for the {rec.candidate_role.replace('_', ' ').lower()}")
    if rec.status != "OPEN":
        raise Problem(409, "ILLEGAL_TRANSITION", f"Recommendation already {rec.status}")
    if not accepted and not comment:
        raise Problem(422, "COMMENT_REQUIRED", "Say why the recommendation is rejected; it trains the agent")
    rec.status = "ACCEPTED" if accepted else "REJECTED"
    rec.decided_by, rec.decided_at, rec.feedback_comment = p.user_id, clock.now(), comment
    run = session.get(AgentRun, rec.agent_run_id)
    run.human_feedback = rec.status
    audit.record(session, rec.object_type, rec.object_id, "RECOMMENDATION_" + rec.status, object_ref=rec.object_ref,
                 after={"agent": rec.agent_code, "title": rec.title}, reason=comment, ai_ref=f"agent-run:{run.id}")
    return rec


def get_recommendation(session: Session, rec_id: str) -> Recommendation:
    try:
        rec = session.get(Recommendation, uuid.UUID(rec_id))
    except ValueError:
        rec = None
    if rec is None:
        raise not_found("Recommendation", rec_id)
    return rec
