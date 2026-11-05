"""Governance workflows of M01 around the cube: the steward queue, maverick rules and hits, supplier duplicates, category plans, and the
scheduled jobs that keep the cube and its SLAs current.

* Steward queue     priority (value) and SLA ageing, bulk reclassification, keyword learning, four-eyes above a value
                    (the single decision is ``spend.decide_review``).
* Maverick          rules as effective-dated versions (rule set MAVERICK-RULES: active, severity, owner role, SLA days, escalation role), hit
                    worklist with lifecycle (OPEN -> DISPOSED | RECOVERY_OPEN -> RESOLVED), SLA escalation, repeat offenders, savings at risk.
* Duplicates        clusters by PAN, GSTIN, bank account and name; a steward proposes a merge, a second person approves it as a workflow task,
                    and the approval records the corporate-parent link (the cube then rolls the records up). Nothing is merged automatically
                    and no supplier record is deleted or blocked.
* Category plans    validation, edit, submission, rejection, revision (versions) and the links to the sourcing pipeline.
"""
import hashlib
import re
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from types import SimpleNamespace
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.pic.models import (
    CategoryPlan, ClassificationReview, MaverickHit, MaverickRule, RuleSet, SavingsInitiative, SourcingEvent, SpendDuplicateCluster, SpendLine, Supplier,
    SupplierBankAccount, Task, TaxonomyNode,
)
from app.pic.platform import audit, clock, rules, workflow
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem, not_found
from app.pic.services import jobs, spend, spend_cube, spend_scope
from app.pic.services.common import principal

STEWARD_ROLES = {"CATEGORY_MANAGER", "MDM_STEWARD", "PROCUREMENT_HEAD"}
PLAN_EDITORS = {"CATEGORY_MANAGER", "PROCUREMENT_HEAD", "CPO"}
LEVER_CATALOGUE = sorted({lever for levers in spend.LEVERS.values() for lever in levers})


# ================================================================ steward queue
def review_queue(session: Session, status: str = "OPEN", *, sort: str = "value", limit: int = 100, offset: int = 0, overdue: Optional[bool] = None,
                 min_value: Optional[int] = None, supplier: Optional[str] = None, text_: Optional[str] = None) -> dict:
    """The classification queue with value, age and SLA, restricted to the reader's scope; ``summary`` covers the whole filtered queue."""
    if sort not in ("value", "due", "confidence", "age"):
        raise Problem(422, "INVALID_SORT", "sort must be value, due, confidence or age")
    if not 1 <= limit <= 500 or offset < 0:
        raise Problem(422, "INVALID_PAGE", "limit must be 1-500 and offset 0 or more")
    R, L = ClassificationReview, SpendLine
    now = clock.now()
    base = spend._scoped_to_line(session, select(R).where(R.status == status), R.spend_line_id)
    if overdue is True:
        base = base.where(R.due_at < now)
    elif overdue is False:
        base = base.where((R.due_at >= now) | R.due_at.is_(None))
    if min_value is not None:
        base = base.where(R.value_group_minor >= min_value)
    if text_:
        base = base.where(R.description.ilike("%" + text_.replace("%", r"\%").replace("_", r"\_") + "%"))
    if supplier:
        base = base.where(R.spend_line_id.in_(select(L.id).where(L.supplier_id.in_(spend_cube._codes_to_ids(session, [supplier]) or [spend_cube.NIL]))))
    order = {"value": (R.value_group_minor.desc().nulls_last(), R.id), "due": (R.due_at.asc().nulls_last(), R.id),
             "confidence": (R.confidence.asc(), R.id), "age": (R.created_at.asc(), R.id)}[sort]
    total = session.execute(select(func.count()).select_from(base.subquery())).scalar()
    rows = session.execute(base.order_by(*order).limit(limit).offset(offset)).scalars().all()
    lines = {l.id: l for l in session.execute(select(L).where(L.id.in_([r.spend_line_id for r in rows] or [spend_cube.NIL]))).scalars()}
    suppliers = {s.id: (s.code, s.legal_name) for s in session.execute(select(Supplier).where(Supplier.id.in_([l.supplier_id for l in lines.values()] or [spend_cube.NIL]))).scalars()}
    threshold = int(spend.gov(session)["fourEyesAboveMinor"])
    items = []
    for r in rows:
        line = lines.get(r.spend_line_id)
        age = (now - r.created_at).total_seconds() / 86400 if r.created_at else 0
        sup = suppliers.get(line.supplier_id, ("?", "")) if line else ("?", "")
        items.append({**{k: getattr(r, k) for k in ("invoice_ref", "description", "proposed_category", "status", "decided_category", "channel", "first_category")},
                      "id": str(r.id), "confidence": str(r.confidence), "alternatives": r.alternatives, "valueMinor": r.value_group_minor or 0,
                      "dueAt": r.due_at.isoformat() if r.due_at else None, "overdue": bool(r.due_at and r.due_at < now and r.status in ("OPEN", "PENDING_SECOND")),
                      "ageDays": round(age, 1), "fourEyes": bool((r.value_group_minor or 0) >= threshold), "supplier": sup[0], "supplierName": sup[1],
                      "plant": line.plant if line else None, "period": line.period if line else None, "currency": line.currency if line else None,
                      "amountMinor": line.amount_minor if line else None, "firstDecidedBy": str(r.first_decided_by) if r.first_decided_by else None,
                      "learnedKeyword": r.learned_keyword})
    return {"total": int(total), "items": items, "summary": queue_summary(session), "fourEyesAboveMinor": threshold}


def queue_summary(session: Session) -> dict:
    R = ClassificationReview
    now = clock.now()
    rows = session.execute(spend._scoped_to_line(session, select(R.status, func.count(), func.coalesce(func.sum(R.value_group_minor), 0)).group_by(R.status), R.spend_line_id)).all()
    open_rows = session.execute(spend._scoped_to_line(session, select(R.created_at, R.due_at, R.value_group_minor).where(R.status.in_(("OPEN", "PENDING_SECOND"))), R.spend_line_id)).all()
    ages = [(now - c).total_seconds() / 86400 for c, _, _ in open_rows if c]
    overdue = [v or 0 for _, d, v in open_rows if d and d < now]
    buckets = {"0-2": 0, "3-5": 0, "6-10": 0, ">10": 0}
    for a in ages:
        buckets["0-2" if a <= 2 else "3-5" if a <= 5 else "6-10" if a <= 10 else ">10"] += 1
    decided = {s: n for s, n, _ in rows}
    judged = decided.get("ACCEPTED", 0) + decided.get("RECLASSIFIED", 0)
    return {"byStatus": {s: {"count": n, "valueMinor": int(v)} for s, n, v in rows}, "open": len(open_rows), "overdue": len(overdue), "overdueValueMinor": int(sum(overdue)),
            "oldestDays": round(max(ages), 1) if ages else 0, "averageAgeDays": round(sum(ages) / len(ages), 1) if ages else 0, "ageBuckets": buckets,
            "acceptRatePct": spend_cube._pct(decided.get("ACCEPTED", 0), judged) if judged else None}


def bulk_reclassify(session: Session, category: str, *, review_ids: Optional[list] = None, text_: Optional[str] = None, supplier: Optional[str] = None,
                    comment: str, learn_keyword: Optional[str] = None, reason: Optional[str] = None) -> dict:
    """Decide many open reviews with one category (explicit ids, or every open review matching a description text / supplier). Each review is a
    normal decision (roles, scope, four-eyes above the value: those are parked as the first decision), done in its own savepoint, with a result
    per row. The keyword is taught once, from the first successful row. At most ``bulkReclassifyMax`` reviews per call."""
    p = principal(session)
    if not set(p.roles) & STEWARD_ROLES:
        raise Problem(403, "FORBIDDEN", "Spend classification is reviewed by a category manager or data steward", rule_ref="M01")
    if not comment or len(comment.strip()) < 5:
        raise Problem(422, "COMMENT_REQUIRED", "A bulk reclassification needs a comment", rule_ref="M01")
    limit = int(spend.gov(session)["bulkReclassifyMax"])
    R = ClassificationReview
    if review_ids:
        ids = [uuid.UUID(str(i)) for i in review_ids]
        query = spend._scoped_to_line(session, select(R).where(R.id.in_(ids), R.status.in_(("OPEN", "PENDING_SECOND"))), R.spend_line_id)
    elif text_ or supplier:
        query = spend._scoped_to_line(session, select(R).where(R.status.in_(("OPEN", "PENDING_SECOND"))), R.spend_line_id)
        if text_:
            query = query.where(R.description.ilike("%" + text_.replace("%", r"\%").replace("_", r"\_") + "%"))
        if supplier:
            query = query.where(R.spend_line_id.in_(select(SpendLine.id).where(SpendLine.supplier_id.in_(spend_cube._codes_to_ids(session, [supplier]) or [spend_cube.NIL]))))
    else:
        raise Problem(422, "SELECTION_REQUIRED", "Give review ids, a description text or a supplier", rule_ref="M01")
    reviews = session.execute(query.order_by(R.created_at, R.id).limit(limit + 1)).scalars().all()
    if len(reviews) > limit:
        raise Problem(422, "BULK_LIMIT", f"More than {limit} reviews match; narrow the selection", rule_ref="M01")
    results, taught = [], False
    for review in reviews:
        try:
            with session.begin_nested():
                spend.decide_review(session, review, category, comment, learn_keyword=None if taught else learn_keyword, reason=reason)
                review.channel = "BULK"      # after the decision: decide_review locks and re-reads the row
            taught = taught or (learn_keyword is not None and review.learned_keyword is not None)
            results.append({"id": str(review.id), "invoice": review.invoice_ref, "status": review.status})
        except Problem as exc:
            results.append({"id": str(review.id), "invoice": review.invoice_ref, "status": "REFUSED", "code": exc.code, "message": exc.detail})
    audit.record(session, "SPEND_REVIEW_BATCH", p.user_id, "BULK_RECLASSIFIED", object_ref=category,
                 after={"category": category, "selected": len(reviews), "decided": sum(1 for r in results if r["status"] in ("ACCEPTED", "RECLASSIFIED")),
                        "parked": sum(1 for r in results if r["status"] == "PENDING_SECOND"), "refused": sum(1 for r in results if r["status"] == "REFUSED"),
                        "keyword": learn_keyword}, reason=comment)
    return {"selected": len(reviews), "results": results}


# ================================================================ maverick rules and hits
def effective_rules(session: Session, on: Optional[date] = None) -> dict:
    """code -> rule (active, severity, owner_role, sla_days, escalate_role) as in force on ``on``: the MaverickRule rows, overridden by the
    effective-dated rule set MAVERICK-RULES when the tenant has versions of it."""
    on = on or clock.today()
    out = {r.code: SimpleNamespace(code=r.code, name=r.name, description=r.description, active=bool(r.active), severity=r.severity, owner_role=r.owner_role,
                                   sla_days=r.sla_days, escalate_role=r.escalate_role) for r in session.execute(select(MaverickRule)).scalars()}
    try:
        body = rules.resolve(session, "MAVERICK-RULES", on).body
    except Problem:
        return out
    for code, over in (body.get("rules") or {}).items():
        if code in out:
            for field, key in (("active", "active"), ("severity", "severity"), ("owner_role", "ownerRole"), ("sla_days", "slaDays"), ("escalate_role", "escalateRole")):
                if key in over:
                    setattr(out[code], field, over[key])
    return out


def rules_view(session: Session, on: Optional[date] = None) -> list:
    base = effective_rules(session, on)
    versions = defaultdict(list)
    for rs in session.execute(select(RuleSet).where(RuleSet.key == "MAVERICK-RULES").order_by(RuleSet.effective_from, RuleSet.version)).scalars():
        for code in (rs.body.get("rules") or {}):
            versions[code].append({"version": rs.version, "effectiveFrom": rs.effective_from.isoformat(),
                                   "effectiveTo": rs.effective_to.isoformat() if rs.effective_to else None, "change": rs.body["rules"][code]})
    hits = dict(session.execute(spend._scoped_to_line(session, select(MaverickHit.rule_code, func.count()).group_by(MaverickHit.rule_code), MaverickHit.spend_line_id)).all())
    return [{"code": r.code, "name": r.name, "description": r.description, "active": r.active, "severity": r.severity, "ownerRole": r.owner_role,
             "slaDays": r.sla_days, "escalateRole": r.escalate_role, "hits": int(hits.get(r.code, 0)), "versions": versions.get(r.code, [])}
            for r in sorted(base.values(), key=lambda x: x.code)]


SEVERITIES = ("Critical", "High", "Medium", "Low")
OWNER_ROLES = ("CATEGORY_MANAGER", "PROCUREMENT_HEAD", "CPO", "FINANCE_CONTROLLER")


def set_rule_version(session: Session, code: str, *, effective_from: date, reason: str, active: Optional[bool] = None, severity: Optional[str] = None,
                     owner_role: Optional[str] = None, sla_days: Optional[int] = None, escalate_role: Optional[str] = None) -> dict:
    """A new effective-dated version of one maverick rule (never an edit): the rule set MAVERICK-RULES carries the overrides of every rule, and
    the version is new for this rule only. The maverick_rule rows stay the baseline; the rule in force for a document is the version effective
    on the document's date (``effective_rules``). Needs admin:rules."""
    p = principal(session)
    if "admin:rules" not in p.scopes:
        raise Problem(403, "FORBIDDEN", "Changing a maverick rule needs the rules administration scope", rule_ref="M01")
    rule = session.execute(select(MaverickRule).where(MaverickRule.code == code)).scalar_one_or_none()
    if rule is None:
        raise not_found("Maverick rule", code)
    if not reason or len(reason.strip()) < 5:
        raise Problem(422, "REASON_REQUIRED", "A rule change needs a reason", rule_ref="P14")
    change = {}
    if active is not None:
        change["active"] = bool(active)
    if severity is not None:
        if severity not in SEVERITIES:
            raise Problem(422, "INVALID_SEVERITY", f"severity must be one of {', '.join(SEVERITIES)}", rule_ref="M01")
        change["severity"] = severity
    if owner_role is not None:
        if owner_role not in OWNER_ROLES:
            raise Problem(422, "INVALID_OWNER_ROLE", f"owner_role must be one of {', '.join(OWNER_ROLES)}", rule_ref="M01")
        change["ownerRole"] = owner_role
    if escalate_role is not None:
        if escalate_role not in OWNER_ROLES:
            raise Problem(422, "INVALID_OWNER_ROLE", f"escalate_role must be one of {', '.join(OWNER_ROLES)}", rule_ref="M01")
        change["escalateRole"] = escalate_role
    if sla_days is not None:
        if isinstance(sla_days, bool) or not isinstance(sla_days, int) or not 1 <= sla_days <= 90:
            raise Problem(422, "INVALID_SLA", "sla_days must be between 1 and 90", rule_ref="M01")
        change["slaDays"] = sla_days
    if not change:
        raise Problem(422, "NOTHING_TO_CHANGE", "Give at least one of active, severity, owner_role, sla_days, escalate_role", rule_ref="M01")
    previous = session.execute(select(RuleSet).where(RuleSet.key == "MAVERICK-RULES", RuleSet.effective_from <= effective_from)
                               .order_by(RuleSet.effective_from.desc(), RuleSet.created_at.desc())).scalars().first()
    body = {"rules": {c: dict(v) for c, v in ((previous.body or {}).get("rules") or {}).items()} if previous else {}}
    body["rules"][code] = {**body["rules"].get(code, {}), **change}
    existing = session.execute(select(RuleSet.version).where(RuleSet.key == "MAVERICK-RULES")).scalars().all()
    version = f"v{len(existing) + 1}"
    clash = session.execute(select(RuleSet).where(RuleSet.key == "MAVERICK-RULES", RuleSet.effective_from == effective_from,
                                                  RuleSet.company_code.is_(None), RuleSet.plant.is_(None), RuleSet.category.is_(None),
                                                  RuleSet.purchase_type.is_(None), RuleSet.supplier_group.is_(None))).scalars().first()
    if clash is not None:
        raise Problem(409, "RULE_VERSION_CONFLICT", f"MAVERICK-RULES@{clash.version} already takes effect on {effective_from.isoformat()}; use a later date", rule_ref="P14")
    session.add(RuleSet(tenant_id=p.tenant_id, key="MAVERICK-RULES", version=version, effective_from=effective_from, body=body,
                        description=f"{code}: {reason}", created_by=p.user_id))
    session.flush()
    audit.record(session, "MAVERICK_RULE", rule.id, "VERSION_CREATED", object_ref=f"{code}@{version}", after={"effectiveFrom": effective_from.isoformat(), **change}, reason=reason)
    return {"code": code, "version": version, "effectiveFrom": effective_from.isoformat(), "change": change}


def lifecycle(hit: MaverickHit) -> str:
    """The BP lifecycle of a hit: OPEN, ACCEPTED (an exception was accepted), RECOVERY (money is being recovered), RESOLVED (closed)."""
    if hit.status == "OPEN":
        return "OPEN"
    if hit.status == "RECOVERY_OPEN":
        return "RECOVERY"
    if hit.status == "RESOLVED":
        return "RESOLVED"
    return "ACCEPTED" if hit.disposition == "ACCEPTED_EXCEPTION" else "RESOLVED"


def hits_view(session: Session, *, status: Optional[str] = None, rule: Optional[str] = None, overdue: Optional[bool] = None, supplier: Optional[str] = None,
              owner: Optional[str] = None, limit: int = 200, offset: int = 0) -> dict:
    """The hit worklist with owner, SLA and escalation; ``owner='me'`` is the caller's own hits (and those of their roles)."""
    if not 1 <= limit <= 500 or offset < 0:
        raise Problem(422, "INVALID_PAGE", "limit must be 1-500 and offset 0 or more")
    H, p, now = MaverickHit, principal(session), clock.now()
    base = spend._scoped_to_line(session, select(H), H.spend_line_id)
    if status:
        base = base.where(H.status == status)
    if rule:
        base = base.where(H.rule_code == rule)
    if supplier:
        base = base.where(H.supplier_id.in_(spend_cube._codes_to_ids(session, [supplier]) or [spend_cube.NIL]))
    if overdue is True:
        base = base.where(H.status == "OPEN", H.due_at < now)
    if owner == "me":
        base = base.where((H.owner_id == p.user_id) | H.owner_role.in_(p.roles or [""]))
    total = session.execute(select(func.count()).select_from(base.subquery())).scalar()
    rows = session.execute(base.order_by(H.amount_group_minor.desc().nulls_last(), H.number).limit(limit).offset(offset)).scalars().all()
    suppliers = {s.id: s.code for s in session.execute(select(Supplier)).scalars()}
    lines = {l.id: l for l in session.execute(select(SpendLine).where(SpendLine.id.in_([h.spend_line_id for h in rows] or [spend_cube.NIL]))).scalars()}
    items = []
    for h in rows:
        line = lines.get(h.spend_line_id)
        items.append({"id": str(h.id), "number": h.number, "rule": h.rule_code, "status": h.status, "lifecycle": lifecycle(h), "disposition": h.disposition,
                      "reasonCode": h.reason_code, "invoice": h.invoice_ref, "po": h.po_ref, "supplier": suppliers.get(h.supplier_id), "category": h.category,
                      "plant": line.plant if line else None, "amountMinor": h.amount_minor, "amountGroupMinor": h.amount_group_minor,
                      "currency": line.currency if line else None, "savingsAtRiskMinor": h.savings_at_risk_minor, "ownerRole": h.owner_role,
                      "ownerId": str(h.owner_id) if h.owner_id else None, "dueAt": h.due_at.isoformat() if h.due_at else None,
                      "overdue": bool(h.status == "OPEN" and h.due_at and h.due_at < now), "escalationLevel": h.escalation_level,
                      "escalatedTo": h.escalated_to_role, "ageDays": round((now - h.created_at).total_seconds() / 86400, 1) if h.created_at else None,
                      "comment": h.comment, "recoveredMinor": h.recovered_minor, "resolvedAt": h.resolved_at.isoformat() if h.resolved_at else None})
    return {"total": int(total), "hits": items, "summary": hits_summary(session)}


def hits_summary(session: Session) -> dict:
    H, now = MaverickHit, clock.now()
    rows = session.execute(spend._scoped_to_line(session, select(H.status, H.rule_code, H.owner_role, H.due_at, H.amount_group_minor, H.savings_at_risk_minor, H.recovered_minor),
                                                 H.spend_line_id)).all()
    by_status, by_rule, by_role = defaultdict(int), defaultdict(lambda: {"count": 0, "open": 0, "valueMinor": 0}), defaultdict(int)
    overdue = at_risk = open_value = recovered = 0
    for status, rule, role, due, value, risk, rec in rows:
        by_status[status] += 1
        slot = by_rule[rule]
        slot["count"] += 1
        slot["valueMinor"] += int(value or 0)
        if status == "OPEN":
            slot["open"] += 1
            by_role[role] += 1
            open_value += int(value or 0)
            at_risk += int(risk or 0)
            overdue += 1 if due and due < now else 0
        recovered += int(rec or 0)
    return {"byStatus": dict(by_status), "byRule": dict(by_rule), "openByOwnerRole": dict(by_role), "open": by_status.get("OPEN", 0), "overdue": overdue,
            "openValueMinor": open_value, "savingsAtRiskMinor": at_risk, "recoveredMinor": recovered}


def repeat_offenders(session: Session, months: int = 12, min_hits: int = 3, limit: int = 50) -> dict:
    """Suppliers and categories with repeated maverick hits in the last ``months`` months: count, distinct rules, value, savings at risk, open
    hits and the latest hit."""
    if not 1 <= months <= 60 or not 1 <= min_hits <= 100:
        raise Problem(422, "INVALID_WINDOW", "months must be 1-60 and min_hits 1-100")
    since = clock.now() - timedelta(days=30 * months)
    H = MaverickHit
    base = spend._scoped_to_line(session, select(H).where(H.created_at >= since), H.spend_line_id)
    hits = session.execute(base).scalars().all()
    suppliers = {s.id: (s.code, s.legal_name) for s in session.execute(select(Supplier)).scalars()}

    def roll(key):
        groups = defaultdict(list)
        for h in hits:
            groups[key(h)].append(h)
        out = []
        for k, items in groups.items():
            if len(items) < min_hits:
                continue
            out.append({"key": k, "hits": len(items), "rules": sorted({h.rule_code for h in items}), "valueMinor": sum(int(h.amount_group_minor or 0) for h in items),
                        "savingsAtRiskMinor": sum(int(h.savings_at_risk_minor or 0) for h in items), "open": sum(1 for h in items if h.status == "OPEN"),
                        "last": max(h.created_at for h in items).date().isoformat() if any(h.created_at for h in items) else None})
        return sorted(out, key=lambda x: (-x["hits"], -x["valueMinor"], str(x["key"])))[:limit]

    by_supplier = roll(lambda h: suppliers.get(h.supplier_id, ("?", ""))[0])
    names_by_code = {c: n for c, n in suppliers.values()}
    for row in by_supplier:
        row["supplier"] = row.pop("key")
        row["name"] = names_by_code.get(row["supplier"])
    by_category = roll(lambda h: h.category)
    for row in by_category:
        row["category"] = row.pop("key")
    return {"since": since.date().isoformat(), "minHits": min_hits, "suppliers": by_supplier, "categories": by_category, "totalHits": len(hits)}


# ================================================================ supplier duplicates
LEGAL_WORDS = re.compile(r"\b(pvt|private|ltd|limited|llp|inc|llc|plc|co|company|corp|corporation|the|gmbh|ag|sa|bv|kk|ltda|and)\b")


def norm_name(name: str) -> str:
    text_ = LEGAL_WORDS.sub(" ", (name or "").lower().replace("&", " and "))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text_)).strip()


def _name_similarity(a: str, b: str) -> float:
    """Token-sorted similarity of two normalised names, 0 when the digits differ (Plant 1 is not Plant 2) or one is empty."""
    if not a or not b or re.findall(r"\d+", a) != re.findall(r"\d+", b):
        return 0.0
    ta, tb = " ".join(sorted(a.split())), " ".join(sorted(b.split()))
    return SequenceMatcher(None, ta, tb).ratio()


NAME_THRESHOLD = 0.92


def find_clusters(session: Session, supplier_ids: Optional[set] = None) -> list[dict]:
    """Groups of supplier records that look like one legal entity: same PAN or GSTIN (score 1.0), same bank account (0.95: IFSC, masked account,
    similar holder), or a name similarity of at least 0.92 on the normalised, token-sorted names (digits must agree). Names are compared inside
    a sliding window of their sorted order, so the scan is linear in the number of suppliers."""
    suppliers = [s for s in session.execute(select(Supplier).order_by(Supplier.code)).scalars() if supplier_ids is None or s.id in supplier_ids]
    parent = {s.id: s.id for s in suppliers}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    signals = defaultdict(list)    # (frozenset pair) -> [(reason, score)]
    def link(a, b, reason, score):
        if find(a.id) != find(b.id):
            parent[find(b.id)] = find(a.id)
        signals[frozenset((a.code, b.code))].append((reason, score))

    for attr, label in (("pan_hash", "same PAN"), ("gstin_hash", "same GSTIN")):
        groups = defaultdict(list)
        for s in suppliers:
            if getattr(s, attr):
                groups[getattr(s, attr)].append(s)
        for group in groups.values():
            for other in group[1:]:
                link(group[0], other, label, 1.0)
    banks = defaultdict(list)
    ids = {s.id: s for s in suppliers}
    for b in session.execute(select(SupplierBankAccount).where(SupplierBankAccount.supplier_id.in_(list(ids) or [spend_cube.NIL]))).scalars():
        banks[(b.ifsc, b.account_masked)].append((ids[b.supplier_id], b.holder_name))
    for group in banks.values():
        distinct = {s.id: (s, h) for s, h in group}
        members = list(distinct.values())
        for other, holder in members[1:]:
            if _name_similarity(norm_name(members[0][1]), norm_name(holder)) >= 0.6 or len(members) == 2:
                link(members[0][0], other, "same bank account", 0.95)
    items = sorted(((s, norm_name(s.legal_name)) for s in suppliers), key=lambda x: (x[1], x[0].code))
    # Each name is prepared once (token-sorted form, its digits and its letter counts). A pair is compared by the full ratio only when the cheap upper
    # bounds of the ratio (the lengths, then the letters the two names share) can still reach the threshold: the result is the same as comparing every
    # pair with SequenceMatcher, at a fraction of the time (this is a read on the supplier screen).
    prepared = []
    for supplier, name in items:
        tokens = " ".join(sorted(name.split()))
        prepared.append((supplier, name, tokens, re.findall(r"\d+", name), Counter(tokens)))
    for i, (a, na, ta, da, ca) in enumerate(prepared):
        if not ta:
            continue
        for b, nb, tb, db_, cb in prepared[i + 1:i + 26]:
            if not tb or da != db_:
                continue
            total = len(ta) + len(tb)
            if 2.0 * min(len(ta), len(tb)) / total < NAME_THRESHOLD or 2.0 * sum((ca & cb).values()) / total < NAME_THRESHOLD:
                continue
            ratio = SequenceMatcher(None, ta, tb).ratio()
            if ratio >= NAME_THRESHOLD:
                link(a, b, f"similar name ({ratio:.2f})", round(ratio, 3))
    groups = defaultdict(list)
    for s in suppliers:
        groups[find(s.id)].append(s)
    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda s: s.code)
        codes = [s.code for s in members]
        reasons, score = [], 0.0
        for pair, found in signals.items():
            if pair <= set(codes):
                for reason, value in found:
                    if reason not in reasons:
                        reasons.append(reason)
                    score = max(score, value)
        out.append({"key": hashlib.sha1("|".join(codes).encode()).hexdigest()[:20], "suppliers": members, "reasons": reasons, "score": round(score, 3)})
    return sorted(out, key=lambda c: c["suppliers"][0].code)


def duplicate_clusters(session: Session, spend_by_supplier: Optional[dict] = None) -> list[dict]:
    """Clusters for the supplier view: not dismissed ones, with spend per member (a scoped reader only sees suppliers that have spend in scope)."""
    spend_by_supplier = spend_by_supplier or {}
    restrict = set(spend_by_supplier) if spend_scope.of(session).restricted else None
    state = {c.cluster_key: c for c in session.execute(select(SpendDuplicateCluster)).scalars()}
    out = []
    for cluster in find_clusters(session, restrict):
        saved = state.get(cluster["key"])
        if saved is not None and saved.status in ("DISMISSED",):
            continue
        members = cluster["suppliers"]
        out.append({"key": cluster["key"], "suppliers": [{"code": s.code, "name": s.legal_name, "spendMinor": int(spend_by_supplier.get(s.id, 0)),
                                                          "parent": None} for s in members],
                    "reason": ", ".join(cluster["reasons"]) or "similar legal name", "reasons": cluster["reasons"], "score": cluster["score"],
                    "status": saved.status if saved else "OPEN", "survivor": saved.survivor_code if saved else None,
                    "proposal": saved.proposal_number if saved else None})
    return out


def scan_duplicates(session: Session) -> dict:
    """Persist the current clusters (new ones OPEN; the decision on a known cluster is kept) with their trailing-12-month spend."""
    p = principal(session)
    if not set(p.roles) & (STEWARD_ROLES | {"SUPPLIER_MANAGER", "CPO"}):
        raise Problem(403, "FORBIDDEN", "Scanning supplier duplicates is for stewards and supplier managers", rule_ref="M01")
    periods = spend._window(session, 12)
    C = spend_cube.C
    spent = {sid: int(v or 0) for sid, v in session.execute(select(C.supplier_id, func.sum(C.amount_group_minor)).where(
        C.period.between(periods[0], periods[-1]), *spend_scope.where(session, C)).group_by(C.supplier_id))}
    new = known = 0
    for cluster in find_clusters(session):
        codes = [s.code for s in cluster["suppliers"]]
        row = session.execute(select(SpendDuplicateCluster).where(SpendDuplicateCluster.cluster_key == cluster["key"])).scalar_one_or_none()
        value = sum(spent.get(s.id, 0) for s in cluster["suppliers"])
        if row is None:
            session.add(SpendDuplicateCluster(tenant_id=p.tenant_id, cluster_key=cluster["key"], supplier_codes=codes, reasons=cluster["reasons"],
                                              score=Decimal(str(cluster["score"])), spend_group_minor=value, status="OPEN", created_by=p.user_id))
            new += 1
        else:
            row.reasons, row.score, row.spend_group_minor = cluster["reasons"], Decimal(str(cluster["score"])), value
            known += 1
    session.flush()
    return {"new": new, "known": known}


MERGE_KIND = "SPEND_SUPPLIER_MERGE"


def propose_merge(session: Session, key: str, survivor_code: str, note: str) -> SpendDuplicateCluster:
    """A steward proposes to treat the cluster's records as one supplier group under ``survivor_code``. A second person (a data steward other than
    the proposer) approves it as a workflow task; the approval records the corporate-parent link, which the cube uses to roll the records up.
    The records themselves are neither merged, blocked nor deleted: the ERP merge stays a master-data decision."""
    p = principal(session)
    if not set(p.roles) & (STEWARD_ROLES | {"SUPPLIER_MANAGER"}):
        raise Problem(403, "FORBIDDEN", "Proposing a supplier merge is for stewards and category managers", rule_ref="M01")
    if not note or len(note.strip()) < 5:
        raise Problem(422, "COMMENT_REQUIRED", "A merge proposal needs a reason", rule_ref="M01")
    cluster = session.execute(select(SpendDuplicateCluster).where(SpendDuplicateCluster.cluster_key == key)).scalar_one_or_none()
    if cluster is None:
        scan_duplicates(session)
        cluster = session.execute(select(SpendDuplicateCluster).where(SpendDuplicateCluster.cluster_key == key)).scalar_one_or_none()
    if cluster is None:
        raise not_found("Duplicate cluster", key)
    if cluster.status not in ("OPEN", "REJECTED"):
        raise Problem(409, "ILLEGAL_TRANSITION", f"Cluster {key[:8]} is {cluster.status}")
    if survivor_code not in cluster.supplier_codes:
        raise Problem(422, "SURVIVOR_NOT_IN_CLUSTER", f"{survivor_code} is not one of {', '.join(cluster.supplier_codes)}", rule_ref="M01")
    cluster.status, cluster.survivor_code, cluster.note, cluster.proposal_number = "PROPOSED", survivor_code, note, f"DUP-{key[:8].upper()}"
    cluster.decided_by = p.user_id
    workflow.start_approval(session, None, MERGE_KIND, object_type="SPEND_DUPLICATE_CLUSTER", object_id=cluster.id, object_ref=cluster.proposal_number,
                            chain=["MDM_STEWARD"], step_id=None, initiator_id=p.user_id, sla_business_days=3,
                            evidence={"suppliers": cluster.supplier_codes, "survivor": survivor_code, "reasons": cluster.reasons, "note": note})
    audit.record(session, "SPEND_DUPLICATE_CLUSTER", cluster.id, "MERGE_PROPOSED", object_ref=cluster.proposal_number,
                 after={"survivor": survivor_code, "suppliers": cluster.supplier_codes}, reason=note)
    return cluster


def dismiss_cluster(session: Session, key: str, note: str) -> SpendDuplicateCluster:
    p = principal(session)
    if not set(p.roles) & (STEWARD_ROLES | {"SUPPLIER_MANAGER"}):
        raise Problem(403, "FORBIDDEN", "Dismissing a duplicate cluster is for stewards and category managers", rule_ref="M01")
    if not note or len(note.strip()) < 5:
        raise Problem(422, "COMMENT_REQUIRED", "Say why these are different suppliers", rule_ref="M01")
    cluster = session.execute(select(SpendDuplicateCluster).where(SpendDuplicateCluster.cluster_key == key)).scalar_one_or_none()
    if cluster is None:
        scan_duplicates(session)
        cluster = session.execute(select(SpendDuplicateCluster).where(SpendDuplicateCluster.cluster_key == key)).scalar_one_or_none()
    if cluster is None:
        raise not_found("Duplicate cluster", key)
    if cluster.status not in ("OPEN", "REJECTED"):
        raise Problem(409, "ILLEGAL_TRANSITION", f"Cluster {key[:8]} is {cluster.status}")
    cluster.status, cluster.note, cluster.decided_by, cluster.decided_at = "DISMISSED", note, p.user_id, clock.now()
    audit.record(session, "SPEND_DUPLICATE_CLUSTER", cluster.id, "DISMISSED", object_ref=key[:8], reason=note)
    return cluster


@workflow.guard_task(MERGE_KIND)
def _merge_guard(session: Session, task: Task, decision: str) -> None:
    p = principal(session)
    cluster = session.get(SpendDuplicateCluster, task.object_id)
    if cluster is not None and cluster.decided_by == p.user_id:
        raise Problem(409, "SOD_CONFLICT", "The proposer of a supplier merge cannot approve it", rule_ref="M01")


@workflow.on_task(MERGE_KIND)
def _merge_decided(session: Session, task: Task, outcome: str) -> None:
    cluster = session.get(SpendDuplicateCluster, task.object_id)
    if cluster is None:
        return
    if outcome != "APPROVED":
        cluster.status, cluster.note = "REJECTED", task.comment or cluster.note
        audit.record(session, "SPEND_DUPLICATE_CLUSTER", cluster.id, "MERGE_REJECTED", object_ref=cluster.proposal_number, reason=task.comment)
        return
    survivor = session.execute(select(Supplier).where(Supplier.code == cluster.survivor_code)).scalar_one()
    for code in cluster.supplier_codes:
        if code == survivor.code:
            continue
        other = session.execute(select(Supplier).where(Supplier.code == code)).scalar_one()
        if other.parent_supplier_id is None and survivor.parent_supplier_id != other.id:
            other.parent_supplier_id = survivor.id
    cluster.status, cluster.decided_by, cluster.decided_at = "MERGE_APPROVED", task.completed_by, clock.now()
    # the cube rolls the records up under the survivor from the next refresh: every period where one of them has spend is marked dirty
    session.flush()
    session.execute(text(
        "INSERT INTO pic.spend_view_dirty (id, tenant_id, created_at, row_version, period, marked_at) "
        "SELECT gen_random_uuid(), CAST(:t AS uuid), :now, 1, p.period, :now FROM (SELECT DISTINCT period FROM pic.spend_line WHERE tenant_id = :t "
        "AND supplier_id IN (SELECT id FROM pic.supplier WHERE tenant_id = :t AND code = ANY(CAST(:codes AS text[])))) p "
        "ON CONFLICT (tenant_id, period) DO UPDATE SET marked_at = EXCLUDED.marked_at"),
        {"t": cluster.tenant_id, "now": clock.now(), "codes": list(cluster.supplier_codes)})
    audit.record(session, "SPEND_DUPLICATE_CLUSTER", cluster.id, "MERGE_APPROVED", object_ref=cluster.proposal_number,
                 after={"survivor": cluster.survivor_code, "linked": [c for c in cluster.supplier_codes if c != cluster.survivor_code]}, reason=task.comment)


# ================================================================ category plans
def validate_plan(session: Session, plan: CategoryPlan) -> list[str]:
    """Why a plan cannot be approved: budget, savings target against the addressable spend, levers from the catalogue, dated waves."""
    errors = []
    settings = spend.gov(session)
    if plan.budget_minor is None or plan.budget_minor < 0:
        errors.append("the budget must be zero or more")
    if plan.savings_target_minor is None or plan.savings_target_minor < 0:
        errors.append("the savings target must be zero or more")
    if plan.budget_minor is not None and plan.savings_target_minor is not None and plan.savings_target_minor > plan.budget_minor:
        errors.append("the savings target cannot exceed the budget")
    if plan.addressable_minor is not None and plan.savings_target_minor is not None:
        cap = int(Decimal(plan.addressable_minor) * Decimal(str(settings["planMaxSavingsPct"])) / 100)
        if plan.savings_target_minor > cap:
            errors.append(f"the savings target {plan.savings_target_minor} is above {settings['planMaxSavingsPct']}% of the category's addressable spend ({cap})")
    catalogue = set(LEVER_CATALOGUE) | set(settings.get("leverCatalogue") or [])
    if not plan.levers:
        errors.append("name at least one lever")
    for lever in plan.levers or []:
        if lever not in catalogue:
            errors.append(f"lever '{lever}' is not in the lever catalogue")
    if plan.savings_by_lever:
        stray = sorted(set(plan.savings_by_lever) - set(plan.levers or []))
        if stray:
            errors.append(f"savings are split over levers the plan does not use: {', '.join(stray)}")
        if any((not isinstance(v, int) or v < 0) for v in plan.savings_by_lever.values()):
            errors.append("each lever's savings must be an amount of zero or more")
        elif plan.savings_target_minor is not None and sum(plan.savings_by_lever.values()) != plan.savings_target_minor:
            errors.append(f"the savings by lever add up to {sum(plan.savings_by_lever.values())}, not to the target {plan.savings_target_minor}")
    if not 0 <= float(plan.profit_impact) <= 10 or not 0 <= float(plan.supply_risk) <= 10:
        errors.append("profit impact and supply risk are scores between 0 and 10")
    if plan.kraljic not in spend.LEVERS:
        errors.append(f"the Kraljic position must be one of {', '.join(spend.LEVERS)}")
    waves = plan.wave_plan or []
    if not waves and not plan.waves:
        errors.append("the plan needs a wave plan")
    start_month = spend_cube.fiscal_start_month(session)
    try:
        fy_start = date(int(plan.fiscal_year[:4]), start_month, 1)
    except (ValueError, TypeError):
        fy_start = None
    min_days = int(settings["planWaveMinDays"])
    for n, wave in enumerate(waves, start=1):
        try:
            start, end = date.fromisoformat(wave["start"]), date.fromisoformat(wave["end"])
        except (KeyError, ValueError, TypeError):
            errors.append(f"wave {n} needs a start and an end date (YYYY-MM-DD)")
            continue
        if not str(wave.get("name") or "").strip():
            errors.append(f"wave {n} needs a name")
        if end < start:
            errors.append(f"wave {n} ends before it starts")
        elif (end - start).days + 1 < min_days:
            errors.append(f"wave {n} is shorter than {min_days} days")
        if fy_start is not None and (start < fy_start or end > _add_months_end(fy_start, 24)):
            errors.append(f"wave {n} lies outside {plan.fiscal_year} and the following year")
    return errors


def _add_months_end(start: date, months: int) -> date:
    index = start.year * 12 + start.month - 1 + months
    return date(index // 12, index % 12 + 1, 1) - timedelta(days=1)


def _editable(session: Session, plan: CategoryPlan) -> None:
    p = principal(session)
    if not (set(p.roles) & PLAN_EDITORS):
        raise Problem(403, "FORBIDDEN", "Category plans are edited by the category manager, procurement head or CPO", rule_ref="M01")
    if plan.owner_id != p.user_id and not set(p.roles) & {"PROCUREMENT_HEAD", "CPO"}:
        raise Problem(403, "FORBIDDEN", f"{plan.number} belongs to its owner", rule_ref="M01")
    if not spend_scope.allows_category(session, plan.category):
        raise Problem(403, "FORBIDDEN", f"{plan.category} is outside your spend scope", rule_ref="ABAC")


def update_plan(session: Session, plan: CategoryPlan, **fields) -> CategoryPlan:
    """Edit a draft (or rejected) plan: budget, savings target, levers, wave plan, savings by lever. The edit is validated whole before it is
    kept; changing the levers or the target re-splits the savings over the levers unless a split is given."""
    _editable(session, plan)
    if plan.status not in ("DRAFT", "REJECTED"):
        raise Problem(409, "ILLEGAL_TRANSITION", f"{plan.number} is {plan.status}; revise it to change it")
    before = {k: getattr(plan, k) for k in ("budget_minor", "savings_target_minor", "levers", "wave_plan", "savings_by_lever")}
    for key in ("budget_minor", "savings_target_minor"):
        if fields.get(key) is not None and (isinstance(fields[key], bool) or not isinstance(fields[key], int)):
            raise Problem(422, "INVALID_AMOUNT", f"{key} must be an integer amount in minor units", rule_ref="M01")
    for key, value in fields.items():
        if value is not None:
            setattr(plan, key, value)
    if (fields.get("levers") is not None or fields.get("savings_target_minor") is not None) and fields.get("savings_by_lever") is None:
        plan.savings_by_lever = spend.split_by_lever(plan.savings_target_minor or 0, plan.levers or [])
    errors = validate_plan(session, plan)
    if errors:
        session.expire(plan)
        raise Problem(422, "INVALID_PLAN", "; ".join(errors), rule_ref="M01", errors=errors)
    if plan.status == "REJECTED":
        plan.status = "DRAFT"
    audit.record(session, "CATEGORY_PLAN", plan.id, "UPDATED", object_ref=plan.number, before=before,
                 after={k: getattr(plan, k) for k in before})
    return plan


def submit_plan(session: Session, plan: CategoryPlan, comment: Optional[str] = None) -> CategoryPlan:
    """Send a valid draft to approval: it becomes IN_APPROVAL and the procurement head gets a task (never the submitter or the owner)."""
    _editable(session, plan)
    p = principal(session)
    if plan.status not in ("DRAFT", "REJECTED"):
        raise Problem(409, "ILLEGAL_TRANSITION", f"{plan.number} is {plan.status}")
    errors = validate_plan(session, plan)
    if errors:
        raise Problem(422, "INVALID_PLAN", "; ".join(errors), rule_ref="M01", errors=errors)
    plan.status, plan.submitted_by, plan.submitted_at = "IN_APPROVAL", p.user_id, clock.now()
    workflow.start_approval(session, None, PLAN_TASK, object_type="CATEGORY_PLAN", object_id=plan.id, object_ref=plan.number, chain=["PROCUREMENT_HEAD"],
                            step_id=None, initiator_id=p.user_id, sla_business_days=3, exclude=[plan.owner_id],
                            evidence={"category": plan.category, "fiscalYear": plan.fiscal_year, "version": plan.version, "budgetMinor": plan.budget_minor,
                                      "savingsTargetMinor": plan.savings_target_minor, "kraljic": plan.kraljic})
    audit.record(session, "CATEGORY_PLAN", plan.id, "SUBMITTED", object_ref=plan.number, reason=comment, after={"version": plan.version})
    return plan


PLAN_TASK = "CATEGORY_PLAN_APPROVAL"


def _close_tasks(session: Session, plan: CategoryPlan) -> None:
    for task in session.execute(select(Task).where(Task.kind == PLAN_TASK, Task.object_id == plan.id, Task.status == "OPEN")).scalars():
        task.status, task.completed_at = "CANCELLED", clock.now()


def reject_plan(session: Session, plan: CategoryPlan, comment: str) -> CategoryPlan:
    p = principal(session)
    if not set(p.roles) & {"PROCUREMENT_HEAD", "CPO"}:
        raise Problem(403, "FORBIDDEN", "Category plans are decided by the procurement head or CPO", rule_ref="M01")
    if plan.owner_id == p.user_id or plan.submitted_by == p.user_id:
        raise Problem(409, "SOD_CONFLICT", "The owner or submitter of a plan cannot decide it", rule_ref="M01")
    if plan.status not in ("DRAFT", "IN_APPROVAL"):
        raise Problem(409, "ILLEGAL_TRANSITION", f"{plan.number} is {plan.status}")
    if not comment or len(comment.strip()) < 5:
        raise Problem(422, "COMMENT_REQUIRED", "A rejected plan needs the reason", rule_ref="M01")
    plan.status, plan.decision_comment = "REJECTED", comment
    _close_tasks(session, plan)
    audit.record(session, "CATEGORY_PLAN", plan.id, "REJECTED", object_ref=plan.number, reason=comment)
    return plan


def revise_plan(session: Session, plan: CategoryPlan, comment: str) -> CategoryPlan:
    """A new draft version of an approved plan (the approved one stays in force until the revision is approved and supersedes it)."""
    _editable(session, plan)
    p = principal(session)
    if plan.status != "APPROVED":
        raise Problem(409, "ILLEGAL_TRANSITION", f"Only an approved plan is revised; {plan.number} is {plan.status}")
    if not comment or len(comment.strip()) < 5:
        raise Problem(422, "COMMENT_REQUIRED", "A revision needs the reason", rule_ref="M01")
    open_ = session.execute(select(CategoryPlan.number).where(CategoryPlan.category == plan.category, CategoryPlan.fiscal_year == plan.fiscal_year,
                                                             CategoryPlan.status.in_(("DRAFT", "IN_APPROVAL")))).scalars().first()
    if open_:
        raise Problem(409, "REVISION_OPEN", f"{open_} is already open for {plan.category} {plan.fiscal_year}", rule_ref="M01")
    latest = session.execute(select(func.max(CategoryPlan.version)).where(CategoryPlan.category == plan.category, CategoryPlan.fiscal_year == plan.fiscal_year)).scalar()
    clone = CategoryPlan(tenant_id=plan.tenant_id, number=next_number(session, "CATEGORY_PLAN"), category=plan.category, fiscal_year=plan.fiscal_year,
                         spend_minor=plan.spend_minor, profit_impact=plan.profit_impact, supply_risk=plan.supply_risk, kraljic=plan.kraljic,
                         evidence={**plan.evidence, "revisionOf": plan.number, "revisionReason": comment}, levers=list(plan.levers), waves=list(plan.waves),
                         budget_minor=plan.budget_minor, savings_target_minor=plan.savings_target_minor, owner_id=p.user_id, status="DRAFT",
                         version=int(latest) + 1, supersedes_id=plan.id, addressable_minor=plan.addressable_minor, wave_plan=list(plan.wave_plan or []),
                         savings_by_lever=dict(plan.savings_by_lever or {}), created_by=p.user_id)
    session.add(clone)
    session.flush()
    audit.record(session, "CATEGORY_PLAN", clone.id, "REVISED", object_ref=clone.number, after={"supersedes": plan.number, "version": clone.version}, reason=comment)
    return clone


@workflow.guard_task(PLAN_TASK)
def _plan_guard(session: Session, task: Task, decision: str) -> None:
    p = principal(session)
    plan = session.get(CategoryPlan, task.object_id)
    if plan is not None and p.user_id in (plan.owner_id, plan.submitted_by):
        raise Problem(409, "SOD_CONFLICT", "The owner or submitter of a category plan cannot approve or reject it", rule_ref="M01")


@workflow.on_task(PLAN_TASK)
def _plan_decided(session: Session, task: Task, outcome: str) -> None:
    plan = session.get(CategoryPlan, task.object_id)
    if plan is None or plan.status != "IN_APPROVAL":
        return
    if outcome == "APPROVED":
        spend.approve_plan(session, plan, task.comment)
    else:
        plan.status, plan.decision_comment = "REJECTED", task.comment
        audit.record(session, "CATEGORY_PLAN", plan.id, "REJECTED", object_ref=plan.number, reason=task.comment)


def pipeline_links(session: Session, plan: CategoryPlan) -> dict:
    """Sourcing events and savings initiatives in the plan's category (by reference only; the sourcing module owns them)."""
    events = session.execute(select(SourcingEvent).where(SourcingEvent.category == plan.category).order_by(SourcingEvent.created_at.desc()).limit(50)).scalars().all()
    initiatives = session.execute(select(SavingsInitiative).where(SavingsInitiative.category == plan.category).order_by(SavingsInitiative.number).limit(50)).scalars().all()
    return {"plan": plan.number, "category": plan.category,
            "sourcingEvents": [{"number": e.number, "type": e.type, "title": e.title, "status": e.status} for e in events],
            "savingsInitiatives": [{"number": i.number, "title": i.title, "stage": i.stage} for i in initiatives]}


# ================================================================ rule validation (admin rules API hook)
def validate_rule(key: str, body: dict) -> list[str]:
    """Errors in a new version of SPEND-GOVERNANCE or MAVERICK-RULES (POST /v1/admin/rules): empty when usable."""
    errors: list[str] = []
    if key == "MAVERICK-RULES":
        if not isinstance(body, dict) or not isinstance(body.get("rules"), dict):
            return ["the body must be {\"rules\": {CODE: {...}}}"]
        known = {c for c, *_ in spend.MAVERICK_RULES}
        for code, over in body["rules"].items():
            if code not in known:
                errors.append(f"unknown maverick rule {code}")
                continue
            if not isinstance(over, dict) or set(over) - {"active", "severity", "ownerRole", "slaDays", "escalateRole"}:
                errors.append(f"{code}: allowed keys are active, severity, ownerRole, slaDays, escalateRole")
                continue
            if "severity" in over and over["severity"] not in SEVERITIES:
                errors.append(f"{code}: severity must be one of {', '.join(SEVERITIES)}")
            for field in ("ownerRole", "escalateRole"):
                if field in over and over[field] not in OWNER_ROLES:
                    errors.append(f"{code}: {field} must be one of {', '.join(OWNER_ROLES)}")
            if "slaDays" in over and (isinstance(over["slaDays"], bool) or not isinstance(over["slaDays"], int) or not 1 <= over["slaDays"] <= 90):
                errors.append(f"{code}: slaDays must be 1-90")
            if "active" in over and not isinstance(over["active"], bool):
                errors.append(f"{code}: active must be true or false")
        return errors
    if key != "SPEND-GOVERNANCE":
        return errors
    if not isinstance(body, dict):
        return ["the body must be an object"]
    minor = ("oneTimeVendorLimitMinor", "fourEyesAboveMinor", "acceptExceptionLimitMinor", "exportMaxRows", "bulkReclassifyMax", "outlierAmountMinor")
    for name in minor:
        if name in body and (isinstance(body[name], bool) or not isinstance(body[name], int) or body[name] < 0):
            errors.append(f"{name} must be an integer of zero or more")
    for name, low, high in (("classificationThreshold", 0.0, 1.0), ("overInvoicedTolerancePct", 0.0, 100.0), ("aggregationSavingPct", 0.0, 100.0),
                            ("contractSavingPct", 0.0, 100.0), ("planMaxSavingsPct", 0.0, 100.0), ("paretoA", 0.0, 100.0), ("paretoB", 0.0, 100.0)):
        if name in body:
            try:
                value = float(body[name])
                if not low <= value <= high:
                    errors.append(f"{name} must be between {low:g} and {high:g}")
            except (TypeError, ValueError):
                errors.append(f"{name} must be a number")
    if "fiscalYearStartMonth" in body and (isinstance(body["fiscalYearStartMonth"], bool) or not isinstance(body["fiscalYearStartMonth"], int)
                                           or not 1 <= body["fiscalYearStartMonth"] <= 12):
        errors.append("fiscalYearStartMonth must be 1-12")
    for name in ("reviewSlaDays", "staleFeedHours", "fxMaxAgeDays", "planWaveMinDays"):
        if name in body and (isinstance(body[name], bool) or not isinstance(body[name], int) or body[name] < 1):
            errors.append(f"{name} must be an integer of 1 or more")
    if "paretoA" in body and "paretoB" in body and not errors and float(body["paretoA"]) >= float(body["paretoB"]):
        errors.append("paretoA must be below paretoB")
    return errors


# ================================================================ scheduled jobs
@jobs.job("spend-cube-refresh", name="Spend cube refresh", schedule="*/5 * * * *", timeout_seconds=900,
          description="Rebuilds the periods of the spend cube whose lines changed since the last refresh (near-real-time, TD AD-04: less than 5 minutes), "
                      "and the whole cube when it was never built. A read refreshes a small backlog itself; this job catches up a large one.")
def spend_cube_refresh(ctx: jobs.JobContext) -> dict:
    if ctx.dry_run:
        return {"dirtyPeriods": spend_cube.freshness(ctx.session)["dirtyPeriods"]}
    result = spend_cube.refresh_spend_views(ctx.tenant_id, dirty_only=True, session=ctx.session)
    return {"mode": result["cube"]["mode"], "periods": result["cube"]["periods"], "lines": result["cube"]["lines"], "durationMs": result["durationMs"]}


@jobs.job("spend-sla", name="Spend SLA escalation", schedule="15 * * * *", dry_run=True,
          description="Escalates maverick hits past their SLA to the rule's escalation role (two levels) and reports the steward queue ageing.")
def spend_sla(ctx: jobs.JobContext) -> dict:
    if ctx.dry_run:
        due = ctx.session.execute(select(func.count()).select_from(MaverickHit).where(MaverickHit.status == "OPEN", MaverickHit.due_at < ctx.now,
                                                                                    MaverickHit.escalation_level < 2)).scalar()
        return {"wouldEscalate": int(due)}
    escalated = spend.escalate_overdue(ctx.session, ctx.now)
    return {"escalated": len(escalated), "queue": queue_summary(ctx.session)}


@jobs.job("spend-quality", name="Spend data-quality assessment", schedule="0 5 * * *",
          description="Runs the spend-cube data-quality checks and stores the score history (GET /v1/spend/quality/history).")
def spend_quality_job(ctx: jobs.JobContext) -> dict:
    from app.pic.services import spend_quality
    report = spend_quality.assess(ctx.session, persist=not ctx.dry_run)
    return {"score": report["score"], "failing": report["failing"]}


@jobs.job("spend-forecast-snapshot", name="Spend forecast snapshot", schedule="30 5 2 * *", dry_run=True,
          description="Stores the spend forecast as issued (all categories, 6 months ahead) so its real error can be measured against the actuals.")
def spend_forecast_snapshot(ctx: jobs.JobContext) -> dict:
    from app.pic.services import spend_forecast
    if ctx.dry_run:
        return {"series": len(spend_forecast.forecast(ctx.session, None, None, 6)["series"])}
    return spend_forecast.snapshot(ctx.session, 6)
