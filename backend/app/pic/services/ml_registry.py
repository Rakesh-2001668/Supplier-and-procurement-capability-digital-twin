"""Model registry, evaluation runs and drift monitoring (Technical Document §13, Blueprint §25).

Every model that influences a business object is a row in ``ml_model`` (code + version) with its parameters, training data
description, offline metrics and a status:

    CANDIDATE  trained and stored, not used
    ACTIVE     the one version per code the platform uses (the rest of the platform asks ``effective_version``)
    RETIRED    replaced by a later ACTIVE version (kept: the fallback target)
    SUSPENDED  taken out by a drift alert or by an administrator; the previous version is active again

Built-in baselines (rules, exponential smoothing, the seeded twin) are registered as versions too, so "fall back to the
previous version" always has a target. Drift monitors compare the live feature distributions with the training baseline (PSI)
and the live accuracy with the offline accuracy; an alert beyond the threshold suspends the model and re-activates its
predecessor automatically (agents.py kill switch semantics: a human re-enables a suspended version deliberately).
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import MlDriftEvent, MlEvalRun, MlModel
from app.pic.platform import audit, clock, outbox
from app.pic.platform.errors import Problem, not_found
from app.pic.services import ml_core

PSI_ALERT = 0.25
PSI_WARN = 0.10
ACCURACY_DROP_ALERT = 0.10          # absolute drop against the offline accuracy
STATUSES = ("CANDIDATE", "ACTIVE", "RETIRED", "SUSPENDED")

# code -> (built-in baseline version, kind, description, version shipped in code that becomes active when nothing is registered)
BASELINES = {
    "demand_forecast": ("demand-es-v1", "STATISTICAL", "Exponential smoothing, alpha from rule DEMAND-SENSING", "demand-sgb-v1"),
    "late_delivery": ("eta-v3", "RULES", "Seeded twin late-delivery probability (Supplier Capability Twin snapshot)", None),
    "price_trend": ("price-trend-none", "RULES", "No trend model: last price", "price-holt-v1"),
    "invoice_exception_cause": ("exception-rules-v1", "RULES", "Rules by exception type (suggested action)", "exc-nb-v1"),
    "supplier_dedup": ("dedup-rules-v1", "RULES", "F8-03 name ratio and SPD-03 clusters", "dedup-emb-v1"),
    "spend_classification": ("keywords-v1", "RULES", "Keyword evidence plus supplier prior (spend.classify_text)", None),
    "copilot": ("copilot-rules-v1", "RULES", "Deterministic answers from SQL tools", None),
}


# ---------------------------------------------------------------- registry
def get(session: Session, code: str, version: str) -> MlModel:
    model = session.execute(select(MlModel).where(MlModel.code == code, MlModel.version == version)).scalar_one_or_none()
    if model is None:
        raise not_found("Model", f"{code}@{version}")
    return model


def active(session: Session, code: str) -> Optional[MlModel]:
    return session.execute(select(MlModel).where(MlModel.code == code, MlModel.status == "ACTIVE")).scalars().first()


def effective_version(session: Session, code: str) -> str:
    """The version the platform uses for ``code``: the registry's ACTIVE row; without one, the version shipped in code
    (BASELINES[code][3]) or the baseline. A suspended shipped version falls back to the baseline."""
    row = active(session, code)
    if row is not None:
        return row.version
    baseline, _, _, shipped = BASELINES.get(code, (code, "", "", None))
    if shipped:
        suspended = session.execute(select(MlModel.id).where(MlModel.code == code, MlModel.version == shipped, MlModel.status == "SUSPENDED")).first()
        if suspended is None:
            return shipped
    return baseline


def is_baseline(code: str, version: str) -> bool:
    return BASELINES.get(code, (None,))[0] == version


def ensure_baselines(session: Session) -> int:
    """Register the built-in baseline (and shipped) versions for the tenant; idempotent. Called by the tenant bootstrap."""
    created = 0
    tenant_id = current_tenant(session)
    have = {(m.code, m.version) for m in session.execute(select(MlModel)).scalars()}
    activated = {m.code for m in session.execute(select(MlModel).where(MlModel.status == "ACTIVE")).scalars()}
    for code, (baseline, kind, description, shipped) in BASELINES.items():
        if (code, baseline) not in have:
            session.add(MlModel(tenant_id=tenant_id, code=code, version=baseline, kind=kind, status="RETIRED" if shipped else "ACTIVE",
                                description=description, params={}, metrics={}, baseline={}, training={"source": "built-in"},
                                trained_at=clock.now(), activated_at=None if shipped else clock.now()))
            created += 1
            if not shipped:
                activated.add(code)
    session.flush()
    return created


def register(session: Session, *, code: str, version: str, kind: str, params: dict, metrics: dict, baseline: Optional[dict] = None,
             training: Optional[dict] = None, description: Optional[str] = None, activate: bool = False) -> MlModel:
    """Store a trained version (CANDIDATE, or ACTIVE with ``activate``). The same code/version is replaced only while it is a
    CANDIDATE (re-training with the same data gives the same parameters)."""
    row = session.execute(select(MlModel).where(MlModel.code == code, MlModel.version == version)).scalar_one_or_none()
    if row is not None and row.status != "CANDIDATE":
        raise Problem(409, "MODEL_VERSION_EXISTS", f"{code}@{version} is {row.status}; give a new version to a re-trained model")
    previous = active(session, code)
    if row is None:
        row = MlModel(tenant_id=current_tenant(session), code=code, version=version, kind=kind, status="CANDIDATE")
        session.add(row)
    row.kind, row.params, row.metrics = kind, params, metrics
    row.baseline, row.training, row.description = baseline or {}, training or {}, description
    row.trained_at = clock.now()
    row.previous_version = previous.version if previous is not None and previous.version != version else row.previous_version
    session.flush()
    audit.record(session, "ML_MODEL", row.id, "MODEL_REGISTERED", object_ref=f"{code}@{version}",
                 after={"kind": kind, "metrics": metrics, "training": training or {}})
    if activate:
        activate_version(session, code, version, reason="activated at registration")
    return row


def activate_version(session: Session, code: str, version: str, reason: str) -> MlModel:
    target = get(session, code, version)
    if target.status == "SUSPENDED":
        raise Problem(409, "MODEL_SUSPENDED", f"{code}@{version} is suspended ({target.suspended_reason}); re-register it as a new version")
    current = active(session, code)
    if current is not None and current.id != target.id:
        current.status = "RETIRED"
        target.previous_version = current.version
        session.flush()          # the partial unique index allows one ACTIVE version per code: retire before activating
    target.status, target.activated_at, target.suspended_reason = "ACTIVE", clock.now(), None
    session.flush()
    audit.record(session, "ML_MODEL", target.id, "MODEL_ACTIVATED", object_ref=f"{code}@{version}", reason=reason,
                 after={"previous": target.previous_version})
    outbox.emit(session, "ml.model.activated", "ML_MODEL", target.id, f"{code}@{version}", {"code": code, "version": version})
    return target


def suspend(session: Session, code: str, version: str, reason: str, *, fallback: bool = True) -> dict:
    """Take a version out of use and (``fallback``) re-activate the previous one, or the built-in baseline."""
    model = get(session, code, version)
    ensure_baselines(session)
    was_active = model.status == "ACTIVE"
    model.status, model.suspended_reason = "SUSPENDED", reason[:300]
    session.flush()
    fell_back_to = None
    if was_active and fallback:
        target = None
        if model.previous_version:
            target = session.execute(select(MlModel).where(MlModel.code == code, MlModel.version == model.previous_version,
                                                           MlModel.status != "SUSPENDED")).scalar_one_or_none()
        if target is None:
            baseline = BASELINES.get(code, (None,))[0]
            target = session.execute(select(MlModel).where(MlModel.code == code, MlModel.version == baseline)).scalar_one_or_none() if baseline else None
        if target is not None:
            target.status, target.activated_at = "ACTIVE", clock.now()
            fell_back_to = target.version
    session.flush()
    audit.record(session, "ML_MODEL", model.id, "MODEL_SUSPENDED", object_ref=f"{code}@{version}", reason=reason,
                 after={"fallbackTo": fell_back_to})
    outbox.emit(session, "ml.model.suspended", "ML_MODEL", model.id, f"{code}@{version}",
                {"code": code, "version": version, "reason": reason, "fallbackTo": fell_back_to})
    return {"code": code, "version": version, "status": "SUSPENDED", "fallbackTo": fell_back_to}


# ---------------------------------------------------------------- evaluation runs
def record_eval(session: Session, *, code: str, version: str, dataset: str, metrics: dict, gate: Optional[bool] = None,
                details: Optional[dict] = None) -> MlEvalRun:
    run = MlEvalRun(tenant_id=current_tenant(session), code=code, version=version, dataset=dataset, metrics=metrics, gate=gate,
                    details=details or {}, run_at=clock.now())
    session.add(run)
    model = session.execute(select(MlModel).where(MlModel.code == code, MlModel.version == version)).scalar_one_or_none()
    if model is not None:
        model.metrics = {**(model.metrics or {}), dataset: metrics}
    session.flush()
    audit.record(session, "ML_MODEL", model.id if model is not None else run.id, "MODEL_EVALUATED", object_ref=f"{code}@{version}",
                 after={"dataset": dataset, "metrics": metrics, "gate": gate})
    return run


# ---------------------------------------------------------------- drift monitoring
def check_drift(session: Session, code: str, *, features: Optional[dict[str, list[float]]] = None,
                live_accuracy: Optional[float] = None, accuracy_metric: str = "accuracy", auto_fallback: bool = True,
                psi_alert: float = PSI_ALERT, accuracy_drop: float = ACCURACY_DROP_ALERT) -> dict:
    """Compare live data with the ACTIVE version's training baseline.

    ``features`` maps a feature name to its recent values; the baseline stores bin edges and shares per feature
    (``baseline = {"features": {name: {"edges": [...], "shares": [...]}}}``). ``live_accuracy`` is compared with
    ``metrics.<accuracy_metric>`` of the version's offline evaluation. Any alert is stored as a drift event and, with
    ``auto_fallback``, suspends the version and re-activates the previous one."""
    model = active(session, code)
    if model is None or is_baseline(code, model.version):
        return {"code": code, "checked": False, "reason": "no trained version is active", "alerts": []}
    now, events, alerts = clock.now(), [], []
    stored = (model.baseline or {}).get("features", {})
    for name, values in (features or {}).items():
        reference = stored.get(name)
        if not reference or len(values) < 10:
            continue
        value = ml_core.psi(reference["shares"], ml_core.histogram(values, reference["edges"]))
        status = "ALERT" if value >= psi_alert else "OK"
        events.append(MlDriftEvent(tenant_id=model.tenant_id, code=code, version=model.version, monitor="PSI", feature=name,
                                   value=Decimal(str(round(value, 4))), threshold=Decimal(str(psi_alert)), status=status,
                                   details={"n": len(values), "warn": PSI_WARN, "level": "significant" if value >= psi_alert else
                                            "moderate" if value >= PSI_WARN else "stable"}, checked_at=now))
        if status == "ALERT":
            alerts.append(f"PSI {value:.3f} on {name}")
    offline = _offline(model, accuracy_metric)
    if live_accuracy is not None and offline is not None:
        drop = offline - live_accuracy
        status = "ALERT" if drop >= accuracy_drop else "OK"
        events.append(MlDriftEvent(tenant_id=model.tenant_id, code=code, version=model.version, monitor="ACCURACY", feature=accuracy_metric,
                                   value=Decimal(str(round(drop, 4))), threshold=Decimal(str(accuracy_drop)), status=status,
                                   details={"offline": offline, "live": live_accuracy}, checked_at=now))
        if status == "ALERT":
            alerts.append(f"{accuracy_metric} fell from {offline:.3f} to {live_accuracy:.3f}")
    for event in events:
        session.add(event)
    session.flush()
    action = None
    if alerts and auto_fallback:
        action = suspend(session, code, model.version, "drift: " + "; ".join(alerts))
        for event in events:
            if event.status == "ALERT":
                event.action = "FALLBACK"
    audit.record(session, "ML_MODEL", model.id, "DRIFT_CHECKED", object_ref=f"{code}@{model.version}",
                 after={"alerts": alerts, "events": len(events), "action": action})
    if alerts:
        outbox.emit(session, "ml.drift.alert", "ML_MODEL", model.id, f"{code}@{model.version}", {"code": code, "version": model.version, "alerts": alerts})
    return {"code": code, "version": model.version, "checked": True, "events": len(events), "alerts": alerts, "action": action}


def _offline(model: MlModel, metric: str) -> Optional[float]:
    for value in (model.metrics or {}).values():
        if isinstance(value, dict) and isinstance(value.get(metric), (int, float)):
            return float(value[metric])
    value = (model.metrics or {}).get(metric)
    return float(value) if isinstance(value, (int, float)) else None


def feature_baseline(columns: dict[str, list[float]], bins: int = 10) -> dict:
    """Training-time distribution of every feature: quantile bin edges and the share per bin (PSI reference)."""
    out = {}
    for name, values in columns.items():
        if len(values) < 10:
            continue
        edges = ml_core.quantile_edges(values, bins)
        out[name] = {"edges": edges, "shares": ml_core.histogram(values, edges)}
    return {"features": out}


# ---------------------------------------------------------------- views
def view(model: MlModel, with_params: bool = False) -> dict:
    out = {"id": str(model.id), "code": model.code, "version": model.version, "kind": model.kind, "status": model.status,
           "description": model.description, "metrics": model.metrics, "training": model.training, "previousVersion": model.previous_version,
           "trainedAt": model.trained_at.isoformat() if model.trained_at else None,
           "activatedAt": model.activated_at.isoformat() if model.activated_at else None, "suspendedReason": model.suspended_reason,
           "builtIn": is_baseline(model.code, model.version)}
    if with_params:
        out["params"] = model.params
    return out


def registry(session: Session) -> dict:
    models = session.execute(select(MlModel).order_by(MlModel.code, MlModel.trained_at.desc())).scalars().all()
    by_code: dict[str, list] = {}
    for m in models:
        by_code.setdefault(m.code, []).append(view(m))
    codes = []
    for code in sorted(set(by_code) | set(BASELINES)):
        codes.append({"code": code, "effectiveVersion": effective_version(session, code), "versions": by_code.get(code, [])})
    drift = session.execute(select(MlDriftEvent).order_by(MlDriftEvent.checked_at.desc()).limit(50)).scalars().all()
    runs = session.execute(select(MlEvalRun).order_by(MlEvalRun.run_at.desc()).limit(50)).scalars().all()
    return {"models": codes,
            "drift": [{"code": d.code, "version": d.version, "monitor": d.monitor, "feature": d.feature, "value": float(d.value),
                       "threshold": float(d.threshold), "status": d.status, "action": d.action, "details": d.details,
                       "checkedAt": d.checked_at.isoformat()} for d in drift],
            "evaluations": [{"code": r.code, "version": r.version, "dataset": r.dataset, "metrics": r.metrics, "gate": r.gate,
                             "runAt": r.run_at.isoformat()} for r in runs]}


def parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise Problem(422, "INVALID_ID", "Not a valid identifier")
