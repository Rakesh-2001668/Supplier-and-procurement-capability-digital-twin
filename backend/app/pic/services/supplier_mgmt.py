"""M06 supplier management extensions (pending workflows 28-30): segmentation with history, development plans, ESG / cyber assessments and
the responsiveness and ESG scorecard measures.

Segmentation places every supplier in one of four segments from its share of spend and its risk or criticality (rule
``SUPPLIER-SEGMENTATION``); each change is stored with the inputs it was based on and the supplier master carries the current segment.
A development plan is the buyer's structured answer to a CAPA or a weak scorecard: actions with owners and due dates, evidence, reminders
before they fall due, and a review task before the plan is closed with the measured result.
"""
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    AppUser, AuditEvent, Bid, Capa, CategoryPlan, Certificate, DevelopmentAction, DevelopmentPlan, Invitee, Scorecard, SourcingEvent, SpendLine,
    Supplier, SupplierAssessment, SupplierCategoryStatus, SupplierSegment, Task, Timer, InfoRecord, Material, AuctionBid,
)
from app.pic.platform import audit, clock, outbox, rules, workflow
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem, illegal_transition, not_found
from app.pic.platform.serialize import row
from app.pic.services import risk as risk_svc
from app.pic.services.common import principal

SEGMENTS = ("STRATEGIC", "LEVERAGE", "BOTTLENECK", "ROUTINE")
SEGMENT_RULE = "SUPPLIER-SEGMENTATION"
SEGMENT_DEFAULT = {"windowMonths": 12, "highSpendSharePct": 5, "highRiskScore": 40, "criticalQuadrants": ["STRATEGIC", "BOTTLENECK"]}


def _rule(session: Session, key: str, default: dict) -> tuple[str, dict]:
    try:
        rule = rules.resolve(session, key)
        return rule.ref, {**default, **rule.body}
    except Problem as exc:
        if exc.code != "RULE_SET_MISSING":
            raise
        return f"{key}@default", default


# ---------------------------------------------------------------- 28 segmentation
def _spend_by_supplier(session: Session, window_months: int) -> dict:
    today = clock.today()
    cutoff_month = today.year * 12 + today.month - 1 - int(window_months)
    cutoff = f"{cutoff_month // 12:04d}-{cutoff_month % 12 + 1:02d}"
    return {sid: int(amount) for sid, amount in session.execute(
        select(SpendLine.supplier_id, func.sum(SpendLine.amount_minor)).where(SpendLine.period > cutoff).group_by(SpendLine.supplier_id)).all()}


def _criticality(session: Session, supplier: Supplier, critical_quadrants: list, plans: dict, sole: set) -> tuple[str, list]:
    reasons = []
    if supplier.id in sole:
        reasons.append("sole qualified source of at least one material")
    categories = [c for c, in session.execute(select(SupplierCategoryStatus.category).where(
        SupplierCategoryStatus.supplier_id == supplier.id, SupplierCategoryStatus.status.in_(("QUALIFIED", "PREFERRED", "CONDITIONAL")))).all()]
    quadrants = {plans[c] for c in categories if c in plans}
    hit = sorted(quadrants & set(critical_quadrants))
    if hit:
        reasons.append("category plan quadrant " + "/".join(hit).lower())
    level = "HIGH" if reasons else ("MEDIUM" if "LEVERAGE" in quadrants else "LOW")
    return level, reasons


def _sole_source_suppliers(session: Session) -> set:
    qualified = {(r.supplier_id, r.category) for r in session.execute(
        select(SupplierCategoryStatus).where(SupplierCategoryStatus.status.in_(("QUALIFIED", "PREFERRED")))).scalars()}
    sources: dict = {}
    for supplier_id, material_id, category in session.execute(select(InfoRecord.supplier_id, InfoRecord.material_id, Material.category).join(
            Material, Material.id == InfoRecord.material_id)).all():
        if (supplier_id, category) in qualified:
            sources.setdefault(material_id, set()).add(supplier_id)
    return {next(iter(ids)) for ids in sources.values() if len(ids) == 1}


def classify_supplier(spend_share: Decimal, risk_score: int, criticality: str, body: dict) -> tuple[str, str]:
    high_spend = spend_share >= Decimal(str(body["highSpendSharePct"]))
    exposed = risk_score >= int(body["highRiskScore"]) or criticality == "HIGH"
    segment = ("STRATEGIC" if exposed else "LEVERAGE") if high_spend else ("BOTTLENECK" if exposed else "ROUTINE")
    why = (f"{'high' if high_spend else 'low'} spend share {spend_share:.2f}% (threshold {body['highSpendSharePct']}%), "
           f"{'high' if exposed else 'low'} risk/criticality (risk {risk_score}, criticality {criticality})")
    return segment, why


def _set_segment(session: Session, supplier: Supplier, *, segment: str, method: str, share: Decimal, risk: dict, criticality: str,
                 inputs: dict, reason: str, rule_ref: str) -> tuple[SupplierSegment, bool]:
    current = session.execute(select(SupplierSegment).where(SupplierSegment.supplier_id == supplier.id,
                                                            SupplierSegment.effective_to.is_(None))).scalar_one_or_none()
    now = clock.now()
    if current is not None and current.segment == segment and current.method == method:
        current.spend_share, current.risk_score, current.criticality, current.inputs = share, risk["score"], criticality, inputs
        return current, False
    if current is not None:
        current.effective_to = now
    p = session.info.get("principal")
    entry = SupplierSegment(tenant_id=current_tenant(session), supplier_id=supplier.id, segment=segment, method=method, spend_share=share,
                            risk_score=risk["score"], criticality=criticality, inputs=inputs, reason=reason, rule_set_version=rule_ref,
                            effective_from=now, created_by=p.user_id if p else None)
    session.add(entry)
    before = supplier.segment
    supplier.segment = segment
    session.flush()
    audit.record(session, "SUPPLIER", supplier.id, "SEGMENT_CHANGED", object_ref=supplier.code, before={"segment": before},
                 after={"segment": segment, "method": method, "spendSharePct": str(share), "riskScore": risk["score"], "criticality": criticality},
                 reason=reason, rule_set_version=rule_ref)
    outbox.emit(session, "supplier.segment.changed", "SUPPLIER", supplier.id, supplier.code,
                {"supplier": supplier.code, "from": before, "to": segment, "method": method})
    return entry, True


def recompute_segments(session: Session, supplier: Optional[Supplier] = None) -> dict:
    """Recompute the automatic segment of one or all suppliers. A manually set segment stays until it is cleared."""
    ref, body = _rule(session, SEGMENT_RULE, SEGMENT_DEFAULT)
    spend = _spend_by_supplier(session, body["windowMonths"])
    total = sum(spend.values())
    plans = {}
    for plan in session.execute(select(CategoryPlan).order_by(CategoryPlan.fiscal_year)).scalars():
        plans[plan.category] = plan.kraljic
    sole = _sole_source_suppliers(session)
    suppliers = [supplier] if supplier is not None else list(session.execute(select(Supplier).order_by(Supplier.code)).scalars())
    changed, kept_manual, results = 0, 0, []
    for item in suppliers:
        current = session.execute(select(SupplierSegment).where(SupplierSegment.supplier_id == item.id,
                                                                SupplierSegment.effective_to.is_(None))).scalar_one_or_none()
        if current is not None and current.method == "MANUAL":
            kept_manual += 1
            continue
        share = (Decimal(spend.get(item.id, 0)) * 100 / total).quantize(Decimal("0.0001")) if total else Decimal(0)
        risk = risk_svc.supplier_risk_score(session, item)
        criticality, crit_reasons = _criticality(session, item, body["criticalQuadrants"], plans, sole)
        segment, why = classify_supplier(share, risk["score"], criticality, body)
        inputs = {"windowMonths": body["windowMonths"], "supplierSpendMinor": spend.get(item.id, 0), "totalSpendMinor": total,
                  "riskFactors": risk["factors"][:10], "criticalityReasons": crit_reasons}
        entry, did = _set_segment(session, item, segment=segment, method="AUTO", share=share, risk=risk, criticality=criticality, inputs=inputs,
                                  reason=why, rule_ref=ref)
        changed += 1 if did else 0
        results.append({"supplier": item.code, "segment": segment, "changed": did})
    return {"ruleSet": ref, "suppliers": len(suppliers), "changed": changed, "keptManual": kept_manual, "results": results}


def set_segment_manually(session: Session, supplier: Supplier, segment: Optional[str], reason: str) -> dict:
    p = principal(session)
    if not set(p.roles) & {"SUPPLIER_MANAGER", "CATEGORY_MANAGER", "PROCUREMENT_HEAD"}:
        raise Problem(403, "FORBIDDEN", "Segments are set by supplier or category management", rule_ref="SLM-SEGMENT")
    if not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the manual segment", rule_ref="SLM-SEGMENT")
    if segment is None:  # back to the automatic segment
        current = session.execute(select(SupplierSegment).where(SupplierSegment.supplier_id == supplier.id,
                                                                SupplierSegment.effective_to.is_(None))).scalar_one_or_none()
        if current is not None and current.method == "MANUAL":
            current.effective_to = clock.now()
            audit.record(session, "SUPPLIER", supplier.id, "SEGMENT_OVERRIDE_CLEARED", object_ref=supplier.code, reason=reason)
        recompute_segments(session, supplier)
        return segment_view(session, supplier)
    segment = segment.upper()
    if segment not in SEGMENTS:
        raise Problem(422, "INVALID_SEGMENT", f"segment must be one of {', '.join(SEGMENTS)}")
    ref, body = _rule(session, SEGMENT_RULE, SEGMENT_DEFAULT)
    spend = _spend_by_supplier(session, body["windowMonths"])
    total = sum(spend.values())
    share = (Decimal(spend.get(supplier.id, 0)) * 100 / total).quantize(Decimal("0.0001")) if total else Decimal(0)
    risk = risk_svc.supplier_risk_score(session, supplier)
    _set_segment(session, supplier, segment=segment, method="MANUAL", share=share, risk=risk, criticality="HIGH" if risk["score"] >= 40 else "LOW",
                 inputs={"manual": True, "setBy": p.email}, reason=reason.strip(), rule_ref=ref)
    return segment_view(session, supplier)


def segment_view(session: Session, supplier: Supplier) -> dict:
    history = session.execute(select(SupplierSegment).where(SupplierSegment.supplier_id == supplier.id)
                              .order_by(SupplierSegment.effective_from.desc())).scalars().all()
    return {"supplier": supplier.code, "segment": supplier.segment,
            "current": row(history[0]) if history and history[0].effective_to is None else None, "history": [row(h) for h in history]}


def segment_summary(session: Session) -> dict:
    """Spend and supplier count per segment (spend views)."""
    _, body = _rule(session, SEGMENT_RULE, SEGMENT_DEFAULT)
    spend = _spend_by_supplier(session, body["windowMonths"])
    out = {s: {"segment": s, "suppliers": 0, "spendMinor": 0} for s in (*SEGMENTS, "UNSEGMENTED")}
    for supplier in session.execute(select(Supplier)).scalars():
        key = supplier.segment if supplier.segment in SEGMENTS else "UNSEGMENTED"
        out[key]["suppliers"] += 1
        out[key]["spendMinor"] += spend.get(supplier.id, 0)
    total = sum(v["spendMinor"] for v in out.values())
    for v in out.values():
        v["sharePct"] = str((Decimal(v["spendMinor"]) * 100 / total).quantize(Decimal("0.1"))) if total else "0"
    return {"windowMonths": body["windowMonths"], "totalSpendMinor": total, "segments": list(out.values())}


# ---------------------------------------------------------------- 29 development plans
REVIEW_TASK = "DEV_PLAN_REVIEW"
REMINDER_TIMER = "DEV_ACTION_REMINDER"
METRICS = {"OTIF": "otif_pct", "PPM": "ppm", "INVOICE_ACCURACY": "invoice_accuracy_pct", "RFQ_RESPONSE": "rfq_response_hours", "ESG": "esg_score"}
LOWER_IS_BETTER = {"PPM", "RFQ_RESPONSE"}
REMINDER_DAYS = 3


def _manager(session: Session, plan: Optional[DevelopmentPlan] = None) -> None:
    p = principal(session)
    if not set(p.roles) & {"SUPPLIER_MANAGER", "QUALITY_INSPECTOR", "CATEGORY_MANAGER", "PROCUREMENT_HEAD"} or "SUPPLIER_USER" in p.roles:
        raise Problem(403, "FORBIDDEN", "Development plans are managed by supplier, quality or category management", rule_ref="SLM-DEVPLAN")


def latest_metric(session: Session, supplier_id: uuid.UUID, metric: Optional[str]) -> Optional[Decimal]:
    column = METRICS.get(metric or "")
    if column is None:
        return None
    for card in session.execute(select(Scorecard).where(Scorecard.supplier_id == supplier_id).order_by(Scorecard.period.desc())).scalars():
        value = getattr(card, column)
        if value is not None:
            return Decimal(value)
    return None


def _owner(session: Session, supplier: Supplier, owner_id) -> AppUser:
    user = session.get(AppUser, uuid.UUID(str(owner_id)))
    if user is None or not user.active:
        raise Problem(422, "INVALID_OWNER", "The action owner must be an active user")
    if user.supplier_id is not None and user.supplier_id != supplier.id:
        raise Problem(422, "INVALID_OWNER", "A supplier-side owner must belong to the plan's supplier")
    return user


def create_plan(session: Session, supplier: Supplier, *, title: str, objective: str, start_date: date, target_date: date,
                capa: Optional[Capa] = None, metric: Optional[str] = None, target_value: Optional[Decimal] = None,
                actions: Optional[list] = None) -> DevelopmentPlan:
    _manager(session)
    p = principal(session)
    title, objective = (title or "").strip(), (objective or "").strip()
    if len(title) < 3 or len(objective) < 5:
        raise Problem(422, "VALIDATION_FAILED", "Give the plan a title and an objective", rule_ref="SLM-DEVPLAN")
    if target_date <= start_date:
        raise Problem(422, "VALIDATION_FAILED", "The target date must be after the start date", rule_ref="SLM-DEVPLAN")
    if metric is not None and metric not in METRICS:
        raise Problem(422, "INVALID_METRIC", f"metric must be one of {', '.join(METRICS)}", rule_ref="SLM-DEVPLAN")
    if capa is not None and capa.supplier_id != supplier.id:
        raise Problem(422, "INVALID_CAPA", "The CAPA belongs to another supplier", rule_ref="SLM-DEVPLAN")
    if (metric is None) != (target_value is None):
        raise Problem(422, "VALIDATION_FAILED", "Give both the scorecard metric and its target value", rule_ref="SLM-DEVPLAN")
    plan = DevelopmentPlan(
        tenant_id=current_tenant(session), number=next_number(session, "DEVELOPMENT_PLAN"), supplier_id=supplier.id, title=title, objective=objective,
        status="DRAFT", owner_id=p.user_id, start_date=start_date, target_date=target_date, capa_id=capa.id if capa else None, metric=metric,
        baseline_value=latest_metric(session, supplier.id, metric), target_value=target_value, created_by=p.user_id)
    session.add(plan)
    session.flush()
    audit.record(session, "DEVELOPMENT_PLAN", plan.id, "CREATED", object_ref=plan.number,
                 after={"supplier": supplier.code, "capa": capa.number if capa else None, "metric": metric, "target": str(target_value) if target_value else None,
                        "baseline": str(plan.baseline_value) if plan.baseline_value is not None else None})
    for entry in actions or []:
        add_action(session, plan, description=entry["description"], owner_id=entry["owner_id"], due_date=entry["due_date"])
    return plan


def add_action(session: Session, plan: DevelopmentPlan, *, description: str, owner_id, due_date: date) -> DevelopmentAction:
    _manager(session)
    if plan.status not in ("DRAFT", "ACTIVE"):
        raise illegal_transition("Development plan", plan.number, plan.status, "add an action")
    supplier = session.get(Supplier, plan.supplier_id)
    owner = _owner(session, supplier, owner_id)
    if not (description or "").strip():
        raise Problem(422, "VALIDATION_FAILED", "Describe the action", rule_ref="SLM-DEVPLAN")
    if due_date > plan.target_date or due_date < plan.start_date:
        raise Problem(422, "VALIDATION_FAILED", f"The due date must lie within the plan ({plan.start_date} to {plan.target_date})", rule_ref="SLM-DEVPLAN")
    seq = (session.execute(select(func.max(DevelopmentAction.seq)).where(DevelopmentAction.plan_id == plan.id)).scalar() or 0) + 1
    action = DevelopmentAction(tenant_id=plan.tenant_id, plan_id=plan.id, seq=seq, description=description.strip(), owner_id=owner.id,
                               due_date=due_date, status="OPEN", evidence=[], created_by=principal(session).user_id)
    session.add(action)
    session.flush()
    audit.record(session, "DEVELOPMENT_PLAN", plan.id, "ACTION_ADDED", object_ref=plan.number,
                 after={"seq": seq, "owner": owner.email, "due": due_date.isoformat(), "description": action.description[:200]})
    if plan.status == "ACTIVE":
        _arm_reminder(session, action)
    return action


def _arm_reminder(session: Session, action: DevelopmentAction) -> None:
    when = clock.at_ist(action.due_date - timedelta(days=REMINDER_DAYS), 9)
    workflow.create_timer(session, REMINDER_TIMER, "DEVELOPMENT_ACTION", action.id, max(when, clock.now()), {"stage": "DUE_SOON"})
    workflow.create_timer(session, REMINDER_TIMER, "DEVELOPMENT_ACTION", action.id, clock.at_ist(action.due_date + timedelta(days=1), 9),
                          {"stage": "OVERDUE"})


def activate_plan(session: Session, plan: DevelopmentPlan) -> DevelopmentPlan:
    _manager(session)
    if plan.status != "DRAFT":
        raise illegal_transition("Development plan", plan.number, plan.status, "activate")
    actions = session.execute(select(DevelopmentAction).where(DevelopmentAction.plan_id == plan.id)).scalars().all()
    if not actions:
        raise Problem(422, "ACTIONS_REQUIRED", "A development plan needs at least one action before it starts", rule_ref="SLM-DEVPLAN")
    plan.status = "ACTIVE"
    for action in actions:
        _arm_reminder(session, action)
    audit.record(session, "DEVELOPMENT_PLAN", plan.id, "ACTIVATED", object_ref=plan.number, after={"actions": len(actions)})
    supplier = session.get(Supplier, plan.supplier_id)
    _notify(session, [session.get(AppUser, a.owner_id) for a in actions], plan, "DEV_PLAN_STARTED",
            f"Development plan {plan.number} for {supplier.code} has started", "You own at least one action in this plan; see the due dates.")
    return plan


def _notify(session: Session, users, plan: DevelopmentPlan, kind: str, title: str, body: str, dedup: Optional[str] = None) -> None:
    from app.pic.services import notifications

    supplier = session.get(Supplier, plan.supplier_id)
    notifications.notify(session, [u for u in users if u is not None and u.active], kind=kind, title=title, body=body,
                         dedup_key=dedup or f"{kind}:{plan.id}", link=f"/pic/suppliers/{supplier.code}", object_type="DEVELOPMENT_PLAN",
                         object_ref=plan.number)


def _action(session: Session, plan: DevelopmentPlan, seq: int, lock: bool = False) -> DevelopmentAction:
    query = select(DevelopmentAction).where(DevelopmentAction.plan_id == plan.id, DevelopmentAction.seq == seq)
    action = session.execute(query.with_for_update() if lock else query).scalar_one_or_none()
    if action is None:
        raise not_found("Development action", f"{plan.number}/{seq}")
    return action


def _can_work_action(session: Session, plan: DevelopmentPlan, action: DevelopmentAction) -> None:
    p = principal(session)
    if "SUPPLIER_USER" in p.roles:
        if p.supplier_id != plan.supplier_id:
            raise Problem(403, "FORBIDDEN", "You can only act on your own company's plans", rule_ref="SUPPLIER_SCOPE")
        if action.owner_id != p.user_id:
            raise Problem(403, "FORBIDDEN", "Only the action owner can record progress on it", rule_ref="SLM-DEVPLAN")
        return
    if action.owner_id != p.user_id and not set(p.roles) & {"SUPPLIER_MANAGER", "QUALITY_INSPECTOR"}:
        raise Problem(403, "FORBIDDEN", "Only the action owner or supplier management can record progress", rule_ref="SLM-DEVPLAN")


def add_evidence(session: Session, plan: DevelopmentPlan, seq: int, *, note: str, ref: Optional[str] = None) -> DevelopmentAction:
    action = _action(session, plan, seq, lock=True)
    _can_work_action(session, plan, action)
    if plan.status != "ACTIVE" or action.status != "OPEN":
        raise illegal_transition("Development action", f"{plan.number}/{seq}", action.status if plan.status == "ACTIVE" else plan.status, "add evidence")
    if not (note or "").strip():
        raise Problem(422, "VALIDATION_FAILED", "Describe the evidence", rule_ref="SLM-DEVPLAN")
    p = principal(session)
    action.evidence = [*action.evidence, {"note": note.strip(), "ref": (ref or "").strip() or None, "by": p.email, "at": clock.now().isoformat()}]
    audit.record(session, "DEVELOPMENT_PLAN", plan.id, "EVIDENCE_ADDED", object_ref=plan.number, after={"seq": seq, "ref": ref})
    return action


def complete_action(session: Session, plan: DevelopmentPlan, seq: int, *, note: str) -> DevelopmentAction:
    action = _action(session, plan, seq, lock=True)
    _can_work_action(session, plan, action)
    if plan.status != "ACTIVE" or action.status != "OPEN":
        raise illegal_transition("Development action", f"{plan.number}/{seq}", action.status if plan.status == "ACTIVE" else plan.status, "complete")
    if not action.evidence:
        raise Problem(422, "EVIDENCE_REQUIRED", "Attach evidence before completing the action", rule_ref="SLM-DEVPLAN")
    action.status, action.completed_at = "DONE", clock.now()
    for timer in session.execute(select(Timer).where(Timer.kind == REMINDER_TIMER, Timer.object_id == action.id,
                                                              Timer.fired_at.is_(None))).scalars():
        timer.fired_at, timer.payload = clock.now(), {**(timer.payload or {}), "cancelled": True}
    audit.record(session, "DEVELOPMENT_PLAN", plan.id, "ACTION_DONE", object_ref=plan.number, after={"seq": seq}, reason=note)
    open_actions = session.execute(select(func.count()).select_from(DevelopmentAction).where(
        DevelopmentAction.plan_id == plan.id, DevelopmentAction.status == "OPEN")).scalar()
    if open_actions == 0:
        _open_review(session, plan)
    return action


def cancel_action(session: Session, plan: DevelopmentPlan, seq: int, reason: str) -> DevelopmentAction:
    _manager(session)
    action = _action(session, plan, seq, lock=True)
    if action.status != "OPEN":
        raise illegal_transition("Development action", f"{plan.number}/{seq}", action.status, "cancel")
    if not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the reason for cancelling the action", rule_ref="SLM-DEVPLAN")
    action.status = "CANCELLED"
    for timer in session.execute(select(Timer).where(Timer.kind == REMINDER_TIMER, Timer.object_id == action.id,
                                                              Timer.fired_at.is_(None))).scalars():
        timer.fired_at, timer.payload = clock.now(), {**(timer.payload or {}), "cancelled": True}
    audit.record(session, "DEVELOPMENT_PLAN", plan.id, "ACTION_CANCELLED", object_ref=plan.number, after={"seq": seq}, reason=reason)
    if plan.status == "ACTIVE" and not session.execute(select(func.count()).select_from(DevelopmentAction).where(
            DevelopmentAction.plan_id == plan.id, DevelopmentAction.status == "OPEN")).scalar():
        _open_review(session, plan)
    return action


def _open_review(session: Session, plan: DevelopmentPlan) -> None:
    if session.execute(select(Task.id).where(Task.kind == REVIEW_TASK, Task.object_id == plan.id, Task.status == "OPEN")).first():
        return
    supplier = session.get(Supplier, plan.supplier_id)
    workflow.start_approval(session, None, REVIEW_TASK, object_type="DEVELOPMENT_PLAN", object_id=plan.id, object_ref=plan.number,
                            chain=["SUPPLIER_MANAGER"], step_id=None, initiator_id=None, sla_business_days=5,
                            evidence={"supplier": supplier.code, "title": plan.title, "metric": plan.metric,
                                      "baseline": str(plan.baseline_value) if plan.baseline_value is not None else None,
                                      "target": str(plan.target_value) if plan.target_value is not None else None})
    audit.record(session, "DEVELOPMENT_PLAN", plan.id, "REVIEW_REQUESTED", object_ref=plan.number, after={"supplier": supplier.code})


@workflow.on_task(REVIEW_TASK)
def _review_decided(session: Session, task: Task, outcome: str) -> None:
    plan = session.get(DevelopmentPlan, task.object_id)
    if plan is None or plan.status != "ACTIVE":
        return
    if outcome == "APPROVED":
        capa = session.get(Capa, plan.capa_id) if plan.capa_id else None
        if capa is not None and capa.status != "CLOSED":
            # a plan linked to a CAPA completes only when the CAPA is verified closed: send it back instead of closing
            audit.record(session, "DEVELOPMENT_PLAN", plan.id, "REVIEW_BLOCKED", object_ref=plan.number,
                         reason=f"linked CAPA {capa.number} is {capa.status}; verify and close it first")
            _open_review_later(session, plan)
            return
        plan.status, plan.closed_at = "COMPLETED", clock.now()
        plan.result_value = latest_metric(session, plan.supplier_id, plan.metric)
        plan.outcome = task.comment or "Completed"
        audit.record(session, "DEVELOPMENT_PLAN", plan.id, "COMPLETED", object_ref=plan.number,
                     after={"metric": plan.metric, "baseline": str(plan.baseline_value) if plan.baseline_value is not None else None,
                            "result": str(plan.result_value) if plan.result_value is not None else None,
                            "target": str(plan.target_value) if plan.target_value is not None else None,
                            "targetMet": target_met(plan)}, reason=task.comment)
        outbox.emit(session, "supplier.development_plan.completed", "DEVELOPMENT_PLAN", plan.id, plan.number,
                    {"supplierId": str(plan.supplier_id), "targetMet": target_met(plan)})
    else:
        audit.record(session, "DEVELOPMENT_PLAN", plan.id, "REVIEW_REJECTED", object_ref=plan.number, reason=task.comment)


def _open_review_later(session: Session, plan: DevelopmentPlan) -> None:
    """The CAPA is still open: the review is re-opened with a one-week timer so it is not lost."""
    workflow.create_timer(session, "DEV_PLAN_RECHECK", "DEVELOPMENT_PLAN", plan.id, clock.now() + timedelta(days=7), {})


@workflow.on_timer("DEV_PLAN_RECHECK")
def _recheck(session: Session, timer) -> None:
    plan = session.get(DevelopmentPlan, timer.object_id)
    if plan is not None and plan.status == "ACTIVE":
        _open_review(session, plan)


def target_met(plan: DevelopmentPlan) -> Optional[bool]:
    if plan.metric is None or plan.target_value is None or plan.result_value is None:
        return None
    return plan.result_value <= plan.target_value if plan.metric in LOWER_IS_BETTER else plan.result_value >= plan.target_value


def cancel_plan(session: Session, plan: DevelopmentPlan, reason: str) -> DevelopmentPlan:
    _manager(session)
    if plan.status not in ("DRAFT", "ACTIVE"):
        raise illegal_transition("Development plan", plan.number, plan.status, "cancel")
    if not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the reason for cancelling the plan", rule_ref="SLM-DEVPLAN")
    plan.status, plan.closed_at, plan.outcome = "CANCELLED", clock.now(), reason.strip()
    for action in session.execute(select(DevelopmentAction).where(DevelopmentAction.plan_id == plan.id, DevelopmentAction.status == "OPEN")).scalars():
        action.status = "CANCELLED"
    for task in session.execute(select(Task).where(Task.object_id == plan.id, Task.status == "OPEN")).scalars():
        task.status = "CANCELLED"
    for timer in session.execute(select(Timer).where(Timer.kind == REMINDER_TIMER, Timer.fired_at.is_(None),
                                                              Timer.object_id.in_(select(DevelopmentAction.id).where(
                                                                  DevelopmentAction.plan_id == plan.id)))).scalars():
        timer.fired_at, timer.payload = clock.now(), {**(timer.payload or {}), "cancelled": True}
    audit.record(session, "DEVELOPMENT_PLAN", plan.id, "CANCELLED", object_ref=plan.number, reason=reason)
    return plan


@workflow.on_timer(REMINDER_TIMER)
def _remind(session: Session, timer) -> None:
    action = session.get(DevelopmentAction, timer.object_id)
    if action is None or action.status != "OPEN":
        return
    plan = session.get(DevelopmentPlan, action.plan_id)
    if plan is None or plan.status != "ACTIVE":
        return
    stage = (timer.payload or {}).get("stage", "DUE_SOON")
    action.reminders += 1
    owner = session.get(AppUser, action.owner_id)
    overdue = stage == "OVERDUE"
    _notify(session, [owner], plan, "DEV_ACTION_OVERDUE" if overdue else "DEV_ACTION_DUE",
            f"{'Overdue' if overdue else 'Due soon'}: {plan.number} action {action.seq}",
            f"{action.description[:160]} (due {action.due_date.isoformat()}).", dedup=f"DEV_ACTION:{action.id}:{stage}")
    if overdue:  # the plan owner hears about every overdue action too
        _notify(session, [session.get(AppUser, plan.owner_id)], plan, "DEV_ACTION_OVERDUE", f"Overdue: {plan.number} action {action.seq}",
                f"{action.description[:160]} is overdue with {owner.full_name if owner else 'its owner'}.",
                dedup=f"DEV_ACTION_OWNER:{action.id}:{stage}")
    audit.record(session, "DEVELOPMENT_PLAN", plan.id, "REMINDER_SENT", object_ref=plan.number, after={"seq": action.seq, "stage": stage})


def plan_view(session: Session, plan: DevelopmentPlan) -> dict:
    supplier = session.get(Supplier, plan.supplier_id)
    capa = session.get(Capa, plan.capa_id) if plan.capa_id else None
    users = {u.id: u for u in session.execute(select(AppUser).where(AppUser.id.in_(
        [plan.owner_id, *[a.owner_id for a in session.execute(select(DevelopmentAction).where(DevelopmentAction.plan_id == plan.id)).scalars()]])))
        .scalars()}
    today = clock.today()
    actions = session.execute(select(DevelopmentAction).where(DevelopmentAction.plan_id == plan.id).order_by(DevelopmentAction.seq)).scalars().all()
    current = latest_metric(session, plan.supplier_id, plan.metric)
    task = session.execute(select(Task).where(Task.kind == REVIEW_TASK, Task.object_id == plan.id, Task.status == "OPEN")).scalars().first()
    return row(plan, extra={
        "supplier": supplier.code, "supplierName": supplier.legal_name, "capa": capa.number if capa else None,
        "capaStatus": capa.status if capa else None, "owner": users[plan.owner_id].full_name if plan.owner_id in users else None,
        "currentValue": str(current) if current is not None else None, "targetMet": target_met(plan),
        "reviewTask": str(task.id) if task else None,
        "actions": [row(a, extra={"owner": users[a.owner_id].full_name if a.owner_id in users else None,
                                  "ownerEmail": users[a.owner_id].email if a.owner_id in users else None,
                                  "overdue": a.status == "OPEN" and a.due_date < today}) for a in actions],
        "progress": {"done": sum(1 for a in actions if a.status == "DONE"), "total": sum(1 for a in actions if a.status != "CANCELLED")}})


def list_plans(session: Session, supplier: Optional[Supplier] = None, status: Optional[str] = None) -> list[dict]:
    query = select(DevelopmentPlan).order_by(DevelopmentPlan.created_at.desc())
    p = principal(session)
    if "SUPPLIER_USER" in p.roles:
        query = query.where(DevelopmentPlan.supplier_id == p.supplier_id, DevelopmentPlan.status != "DRAFT")
    elif supplier is not None:
        query = query.where(DevelopmentPlan.supplier_id == supplier.id)
    if status:
        query = query.where(DevelopmentPlan.status == status)
    return [plan_view(session, plan) for plan in session.execute(query).scalars()]


# ---------------------------------------------------------------- 30 ESG and cyber assessments
ESG_QUESTIONS = [
    {"id": "E1", "pillar": "Environment", "text": "Environmental management system certified (e.g. ISO 14001)", "weight": 15, "certificates": ["ISO14001"]},
    {"id": "E2", "pillar": "Environment", "text": "Energy use and greenhouse-gas emissions measured and reported", "weight": 10},
    {"id": "E3", "pillar": "Environment", "text": "Waste and effluent handled under statutory consents", "weight": 10},
    {"id": "S1", "pillar": "Social", "text": "Written policy against child and forced labour, applied to sub-suppliers", "weight": 15},
    {"id": "S2", "pillar": "Social", "text": "Occupational health and safety system certified (e.g. ISO 45001)", "weight": 10, "certificates": ["ISO45001"]},
    {"id": "S3", "pillar": "Social", "text": "Statutory wages, PF/ESI and working-hours compliance verified", "weight": 10},
    {"id": "G1", "pillar": "Governance", "text": "Code of conduct and anti-bribery policy in force", "weight": 10},
    {"id": "G2", "pillar": "Governance", "text": "Grievance and whistle-blower channel available to workers", "weight": 10},
    {"id": "G3", "pillar": "Governance", "text": "Annual sustainability or BRSR-style disclosure", "weight": 10},
]
CYBER_QUESTIONS = [
    {"id": "C1", "pillar": "Governance", "text": "Information-security policy approved by management", "weight": 10},
    {"id": "C2", "pillar": "Governance", "text": "Information-security management certified (ISO 27001 or SOC 2)", "weight": 15, "certificates": ["ISO27001", "SOC2"]},
    {"id": "C3", "pillar": "Access", "text": "Multi-factor authentication for remote and privileged access", "weight": 15},
    {"id": "C4", "pillar": "Data", "text": "Data encrypted in transit and at rest", "weight": 15},
    {"id": "C5", "pillar": "Operations", "text": "Security patches applied within the policy window", "weight": 10},
    {"id": "C6", "pillar": "Operations", "text": "Backups tested and stored offline or immutable", "weight": 10},
    {"id": "C7", "pillar": "Response", "text": "Incident-response plan tested in the last 12 months", "weight": 15},
    {"id": "C8", "pillar": "Response", "text": "Security incidents are reported to the buyer without delay (and to CERT-In as required)", "weight": 10},
]
QUESTIONS = {"ESG": ESG_QUESTIONS, "CYBER": CYBER_QUESTIONS}
ANSWER_POINTS = {"YES": Decimal(1), "PARTIAL": Decimal("0.5"), "NO": Decimal(0)}
ASSESSMENT_RULE = "SUPPLIER-ASSESSMENT"
ASSESSMENT_DEFAULT = {"validDays": 365, "minAcceptScore": {"ESG": 40, "CYBER": 40}}


def questionnaire(kind: str) -> list[dict]:
    if kind not in QUESTIONS:
        raise Problem(422, "INVALID_KIND", "kind must be ESG or CYBER")
    return QUESTIONS[kind]


def score_answers(kind: str, answers: dict, held_certificates: set) -> tuple[Decimal, list]:
    total, got, evidence_used = Decimal(0), Decimal(0), []
    for question in questionnaire(kind):
        answer = str(answers.get(question["id"], "")).upper()
        if answer not in ANSWER_POINTS:
            raise Problem(422, "INVALID_ANSWERS", f"Answer {question['id']} with YES, PARTIAL or NO", rule_ref="SLM-ASSESS")
        points = ANSWER_POINTS[answer]
        needed = question.get("certificates")
        if needed and answer == "YES":
            if not held_certificates & set(needed):
                points = Decimal("0.5")  # a YES to a certified management system needs a valid certificate on file
            else:
                evidence_used += sorted(held_certificates & set(needed))
        total += question["weight"]
        got += points * question["weight"]
    return (got * 100 / total).quantize(Decimal("0.01")), sorted(set(evidence_used))


def submit_assessment(session: Session, supplier: Supplier, kind: str, answers: dict, as_of: Optional[date] = None) -> SupplierAssessment:
    p = principal(session)
    if "SUPPLIER_USER" in p.roles and p.supplier_id != supplier.id:
        raise Problem(403, "FORBIDDEN", "You can only submit for your own company", rule_ref="SUPPLIER_SCOPE")
    kind = (kind or "").upper()
    ref, body = _rule(session, ASSESSMENT_RULE, ASSESSMENT_DEFAULT)
    as_of = as_of or clock.today()
    if as_of > clock.today():
        raise Problem(422, "VALIDATION_FAILED", "The assessment date cannot be in the future", rule_ref="SLM-ASSESS")
    today = clock.today()
    held = {c.type for c in session.execute(select(Certificate).where(Certificate.supplier_id == supplier.id,
                                                                      Certificate.expires_on >= today)).scalars()}
    score, evidence = score_answers(kind, answers or {}, held)
    existing = session.execute(select(SupplierAssessment).where(SupplierAssessment.supplier_id == supplier.id, SupplierAssessment.kind == kind,
                                                                SupplierAssessment.as_of == as_of)).scalar_one_or_none()
    if existing is not None:
        if existing.status == "ACCEPTED":
            raise Problem(409, "ASSESSMENT_ACCEPTED", f"The {kind} assessment of {as_of} is already accepted; submit a new one", rule_ref="SLM-ASSESS")
        existing.answers, existing.score, existing.evidence, existing.status = answers, score, evidence, "SUBMITTED"
        existing.submitted_by, existing.rule_set_version = p.user_id, ref
        item = existing
    else:
        item = SupplierAssessment(tenant_id=current_tenant(session), supplier_id=supplier.id, kind=kind, as_of=as_of, answers=answers, score=score,
                                  status="SUBMITTED", evidence=evidence, submitted_by=p.user_id, rule_set_version=ref, created_by=p.user_id)
        session.add(item)
    session.flush()
    audit.record(session, "SUPPLIER", supplier.id, "ASSESSMENT_SUBMITTED", object_ref=supplier.code,
                 after={"kind": kind, "asOf": as_of.isoformat(), "score": str(score), "certificates": evidence}, rule_set_version=ref)
    return item


def review_assessment(session: Session, item: SupplierAssessment, accept: bool, note: str) -> SupplierAssessment:
    p = principal(session)
    if "SUPPLIER_MANAGER" not in p.roles:
        raise Problem(403, "FORBIDDEN", "Assessments are reviewed by supplier management", rule_ref="SLM-ASSESS")
    if item.status != "SUBMITTED":
        raise illegal_transition("Supplier assessment", f"{item.kind} {item.as_of}", item.status, "review")
    if item.submitted_by == p.user_id:
        raise Problem(409, "SOD_CONFLICT", "The reviewer cannot be the person who submitted the assessment", rule_ref="SLM-ASSESS")
    ref, body = _rule(session, ASSESSMENT_RULE, ASSESSMENT_DEFAULT)
    if not accept and not (note or "").strip():
        raise Problem(422, "COMMENT_REQUIRED", "Give the reason for rejecting the assessment", rule_ref="SLM-ASSESS")
    item.status, item.reviewed_by, item.review_note = ("ACCEPTED" if accept else "REJECTED"), p.user_id, (note or "").strip() or None
    if accept:
        item.expires_on = item.as_of + timedelta(days=int(body["validDays"]))
    supplier = session.get(Supplier, item.supplier_id)
    audit.record(session, "SUPPLIER", supplier.id, f"ASSESSMENT_{item.status}", object_ref=supplier.code,
                 after={"kind": item.kind, "asOf": item.as_of.isoformat(), "score": str(item.score),
                        "expiresOn": item.expires_on.isoformat() if item.expires_on else None}, reason=note)
    if accept:
        outbox.emit(session, "supplier.assessment.accepted", "SUPPLIER", supplier.id, supplier.code, {"kind": item.kind, "score": str(item.score)})
        update_scorecard_measures(session, supplier, clock.today().strftime("%Y-%m"))
    return item


def current_assessment(session: Session, supplier_id: uuid.UUID, kind: str) -> Optional[SupplierAssessment]:
    """The latest accepted assessment of the kind that has not expired."""
    today = clock.today()
    return session.execute(select(SupplierAssessment).where(
        SupplierAssessment.supplier_id == supplier_id, SupplierAssessment.kind == kind, SupplierAssessment.status == "ACCEPTED",
        (SupplierAssessment.expires_on.is_(None)) | (SupplierAssessment.expires_on >= today)).order_by(SupplierAssessment.as_of.desc())
        .limit(1)).scalar_one_or_none()


def assessments_view(session: Session, supplier: Supplier) -> dict:
    items = session.execute(select(SupplierAssessment).where(SupplierAssessment.supplier_id == supplier.id)
                            .order_by(SupplierAssessment.as_of.desc())).scalars().all()
    return {"supplier": supplier.code, "items": [row(i) for i in items],
            "questionnaires": {k: [{"id": q["id"], "pillar": q["pillar"], "text": q["text"], "weight": q["weight"],
                                    "certificates": q.get("certificates", [])} for q in v] for k, v in QUESTIONS.items()}}


# ---------------------------------------------------------------- 30 responsiveness and ESG scorecard measures
def _period_bounds(period: str) -> tuple[datetime, datetime]:
    year, month = int(period[:4]), int(period[5:7])
    start = clock.at_ist(date(year, month, 1), 0)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return start, clock.at_ist(nxt, 0)


def update_scorecard_measures(session: Session, supplier: Supplier, period: str) -> Scorecard:
    """RFQ participation and response time, CAPA response time and the ESG score of the supplier for a YYYY-MM period, recomputed from the
    facts (events published in the period, first bid, CAPA response audit entry, accepted ESG assessment). Idempotent."""
    from app.pic.services import supplier as supplier_svc

    start, end = _period_bounds(period)
    events = session.execute(select(SourcingEvent).join(Invitee, Invitee.event_id == SourcingEvent.id).where(
        Invitee.supplier_id == supplier.id, SourcingEvent.published_at >= start, SourcingEvent.published_at < end,
        SourcingEvent.status != "CANCELLED")).scalars().all()
    invited, responded, hours = len(events), 0, []
    for event in events:
        first = session.execute(select(func.min(Bid.submitted_at)).where(Bid.event_id == event.id, Bid.supplier_id == supplier.id)).scalar()
        if first is None and event.type == "REVERSE_AUCTION":
            first = session.execute(select(func.min(AuctionBid.submitted_at)).where(AuctionBid.event_id == event.id,
                                                                                     AuctionBid.supplier_id == supplier.id)).scalar()
        if first is not None:
            responded += 1
            hours.append(Decimal((first - event.published_at).total_seconds()) / 3600)
    capa_hours = []
    for capa in session.execute(select(Capa).where(Capa.supplier_id == supplier.id, Capa.created_at >= start, Capa.created_at < end)).scalars():
        answered = session.execute(select(func.min(AuditEvent.ts)).where(AuditEvent.object_type == "CAPA", AuditEvent.object_id == capa.id,
                                                                          AuditEvent.action == "RESPONDED")).scalar()
        if answered is not None:
            capa_hours.append(Decimal((answered - capa.created_at).total_seconds()) / 3600)
    esg = current_assessment(session, supplier.id, "ESG")
    if not invited and not capa_hours and esg is None:
        existing = session.execute(select(Scorecard).where(Scorecard.supplier_id == supplier.id, Scorecard.period == period)).scalar_one_or_none()
        if existing is None:
            return None
    card = supplier_svc._scorecard(session, supplier.id, period)
    card.rfq_invited, card.rfq_responded = invited, responded
    card.rfq_response_hours = (sum(hours) / len(hours)).quantize(Decimal("0.01")) if hours else None
    card.capa_response_hours = (sum(capa_hours) / len(capa_hours)).quantize(Decimal("0.01")) if capa_hours else None
    card.esg_score = esg.score if esg else None
    session.flush()
    return card


@outbox.consumer("sourcing.bid.submitted", "scorecard-responsiveness")
def _on_bid(session: Session, event) -> None:
    supplier = session.execute(select(Supplier).where(Supplier.code == event.payload.get("supplier"))).scalar_one_or_none()
    sourcing_event = session.get(SourcingEvent, event.object_id)
    if supplier is not None and sourcing_event is not None and sourcing_event.published_at is not None:
        update_scorecard_measures(session, supplier, sourcing_event.published_at.astimezone(clock.IST).strftime("%Y-%m"))


def responsiveness_view(session: Session, supplier: Supplier) -> list[dict]:
    return [{"period": c.period, "rfqInvited": c.rfq_invited, "rfqResponded": c.rfq_responded,
             "rfqResponseRatePct": str((Decimal(c.rfq_responded) * 100 / c.rfq_invited).quantize(Decimal("0.1"))) if c.rfq_invited else None,
             "rfqResponseHours": str(c.rfq_response_hours) if c.rfq_response_hours is not None else None,
             "capaResponseHours": str(c.capa_response_hours) if c.capa_response_hours is not None else None,
             "esgScore": str(c.esg_score) if c.esg_score is not None else None}
            for c in session.execute(select(Scorecard).where(Scorecard.supplier_id == supplier.id).order_by(Scorecard.period)).scalars()]
