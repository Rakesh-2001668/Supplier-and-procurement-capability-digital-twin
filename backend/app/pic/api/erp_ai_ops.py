"""ERP inbound sync (item 55), Supplier Capability Twin (56), risk feeds and sanctions (57), AI gateway, model registry and ML (58)."""
import uuid
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.db import tenant_tx
from app.pic.models import Contract, InvoiceException, MlModel, Supplier
from app.pic.platform import audit, connectors
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.errors import Problem, not_found
from app.pic.services import ai_assist, erp_sync, llm_gateway, ml_models, ml_registry, risk_feeds, sanctions_feed, twin
from app.pic.services.common import by_ref, supplier_ref

router = APIRouter(prefix="/v1")


# ---------------------------------------------------------------- ERP sync (admin screen "ERP sync")
class SyncRunIn(BaseModel):
    system: Optional[str] = Field(default=None, max_length=30, description="Source ERP; default the tenant's target system")
    source: Optional[str] = Field(default=None, pattern="^(AUTO|CONNECTOR|FILE_DROP)$")


class SyncPayloadIn(BaseModel):
    system: Optional[str] = Field(default=None, max_length=30)
    tables: dict = Field(default_factory=dict, description="SAP-table rows by table name (VENDORS: LFA1, LFB1, LFBK, ADRC, T052; MATERIALS: MARA, MAKT, MARC, MBEW)")
    rows: list = Field(default_factory=list, description="Plain rows for the other kinds")


@router.get("/admin/erp-sync", tags=["Integration"])
def erp_sync_overview(p: Principal = Depends(require("admin:integration"))):
    with uow(p) as s:
        return erp_sync.overview(s)


@router.get("/admin/erp-sync/runs", tags=["Integration"])
def erp_sync_runs(kind: Optional[str] = None, limit: int = Query(50, ge=1, le=200), p: Principal = Depends(require("admin:integration"))):
    with uow(p) as s:
        return erp_sync.list_runs(s, kind, limit)


@router.get("/admin/erp-sync/runs/{number}", tags=["Integration"])
def erp_sync_run(number: str, p: Principal = Depends(require("admin:integration"))):
    with uow(p) as s:
        return erp_sync.get_run(s, number)


@router.post("/admin/erp-sync/retry-failed", tags=["Integration"])
def erp_sync_retry(p: Principal = Depends(require("admin:integration"))):
    return {"runs": erp_sync.retry_failed(p.tenant_id)}


@router.post("/admin/erp-sync/{kind}/run", tags=["Integration"])
def erp_sync_run_now(kind: str, body: SyncRunIn, p: Principal = Depends(require("admin:integration")), key: Optional[str] = Depends(idempotency_key)):
    """Run now: pull and apply one object kind. The Idempotency-Key makes a repeated click return the same run."""
    return erp_sync.run(p.tenant_id, kind, system=body.system, source=body.source, mode="ON_DEMAND", triggered_by=p.email, idempotency_key=key)


@router.post("/admin/erp-sync/{kind}/payload", tags=["Integration"])
def erp_sync_payload(kind: str, body: SyncPayloadIn, p: Principal = Depends(require("admin:integration")), key: Optional[str] = Depends(idempotency_key)):
    """Apply rows pushed by an integrator (an ERP extract job, a middleware) through the same validations as a pull."""
    if not body.tables and not body.rows:
        raise Problem(422, "EMPTY_PAYLOAD", "Send tables (VENDORS, MATERIALS) or rows (the other kinds)")
    return erp_sync.run(p.tenant_id, kind, system=body.system, mode="ON_DEMAND", payload={"tables": body.tables, "rows": body.rows}, triggered_by=p.email,
                        idempotency_key=key)


# ---------------------------------------------------------------- Supplier Capability Digital Twin (TD 12.3)
@router.get("/twin/status", tags=["Twin"])
def twin_status(p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return twin.status(s)


@router.get("/suppliers/{code}/twin", tags=["Twin"])
def supplier_twin(code: str, category: str, refresh: bool = False, p: Principal = Depends(require(READ))):
    with uow(p) as s:
        if refresh and "supplier:manage" not in p.scopes:
            raise Problem(403, "FORBIDDEN", "Refreshing from the Twin needs supplier:manage")
        return twin.snapshot(s, supplier_ref(s, code), category, force=refresh)


@router.post("/twin/refresh", tags=["Twin"])
def twin_refresh(p: Principal = Depends(require("supplier:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/twin/refresh", key, {})
        if idem.replay:
            return idem.replay
        return idem.store(twin.refresh_all(s))


@router.post("/twin/scorecards/{period}/write-back", tags=["Twin"])
def twin_write_back(period: str, p: Principal = Depends(require("supplier:manage")), key: Optional[str] = Depends(idempotency_key)):
    if len(period) != 7 or period[4] != "-":
        raise Problem(422, "INVALID_PERIOD", "period must be YYYY-MM")
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/twin/scorecards/{period}/write-back", key, {})
        if idem.replay:
            return idem.replay
        if not twin.configured():
            raise Problem(409, "TWIN_NOT_CONFIGURED", "Set PIC_TWIN_URL to write scorecards back to the Supplier Capability Twin")
        return idem.store(twin.write_back_period(s, period))


# ---------------------------------------------------------------- risk feeds and sanctions (TD 12.3, F8-03)
@router.get("/risk-feeds", tags=["Risk feeds"])
def risk_feed_status(p: Principal = Depends(require_any("supplier:manage", "admin:integration"))):
    with uow(p) as s:
        return risk_feeds.status(s)


@router.get("/risk-feeds/ledger", tags=["Risk feeds"])
def risk_feed_ledger(status: Optional[str] = None, limit: int = Query(100, ge=1, le=500), p: Principal = Depends(require_any("supplier:manage", "admin:integration"))):
    from app.pic.models import RiskFeedEvent
    with uow(p) as s:
        query = select(RiskFeedEvent).order_by(RiskFeedEvent.received_at.desc()).limit(limit)
        if status:
            query = query.where(RiskFeedEvent.status == status.upper())
        return [{"source": r.source, "eventId": r.event_id, "supplier": r.supplier_code, "category": r.category, "severity": r.severity, "status": r.status,
                 "reason": r.reason, "receivedAt": r.received_at.isoformat()} for r in s.execute(query).scalars()]


@router.post("/risk-feeds/{source}/pull", tags=["Risk feeds"])
def risk_feed_pull(source: str, since: Optional[str] = None, p: Principal = Depends(require("supplier:manage")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/risk-feeds/{source}/pull", key, {"since": since})
        if idem.replay:
            return idem.replay
        return idem.store(risk_feeds.pull(s, source, since))


@router.post("/webhooks/risk-feed/{tenant}/{source}", tags=["Risk feeds"], include_in_schema=True)
async def risk_feed_webhook(tenant: str, source: str, request: Request):
    """Provider webhook. No user token: the body must carry ``X-PIC-Signature: sha256=<HMAC of the raw body>`` made with the
    shared secret PIC_RISKFEED_<SOURCE>_WEBHOOK_SECRET. A repeated delivery of an event is acknowledged as DUPLICATE."""
    adapter = risk_feeds.adapters().get(source.upper())
    secret = adapter.webhook_secret() if adapter else None
    if adapter is None or not secret:
        raise Problem(404, "FEED_UNKNOWN", "This risk feed is not configured for webhooks")
    body = await request.body()
    if len(body) > 2_000_000:
        raise Problem(413, "PAYLOAD_TOO_LARGE", "Webhook bodies are limited to 2 MB")
    if not risk_feeds.verify_signature(secret, body, request.headers.get("x-pic-signature")):
        raise Problem(401, "INVALID_SIGNATURE", "The webhook signature does not match")
    tenant_id, code = erp_sync.resolve_tenant(tenant)
    principal = erp_sync._principal(tenant_id, code, f"RISKFEED:{source.upper()}")
    with tenant_tx(tenant_id, principal.user_id, principal) as s:
        return risk_feeds.ingest_webhook(s, source, body)


@router.post("/admin/sanctions/test", tags=["Integration"])
def sanctions_test(p: Principal = Depends(require("admin:integration"))):
    result = sanctions_feed.test()
    with uow(p) as s:
        audit.record(s, "SANCTIONS_LIST", uuid.uuid5(uuid.NAMESPACE_URL, "pic-sanctions:test"), "SANCTIONS_PROVIDER_TESTED", object_ref=result.get("provider"),
                     after={"healthy": result["healthy"], "detail": result["detail"]})
    return result


# ---------------------------------------------------------------- AI: gateway, registry, models (TD 13)
@router.get("/ai/gateway", tags=["AI"])
def ai_gateway(p: Principal = Depends(require("agents:manage"))):
    with uow(p) as s:
        return {**llm_gateway.status(s), "recentCalls": llm_gateway.recent_calls(s, 30)}


@router.get("/ai/models", tags=["AI"])
def ai_models(p: Principal = Depends(require_any("agents:manage", READ))):
    with uow(p) as s:
        return ml_registry.registry(s)


@router.get("/ai/models/{code}/{version}", tags=["AI"])
def ai_model(code: str, version: str, p: Principal = Depends(require("agents:manage"))):
    with uow(p) as s:
        return ml_registry.view(ml_registry.get(s, code, version), with_params=True)


class ModelAction(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


@router.post("/ai/models/{code}/{version}/activate", tags=["AI"])
def ai_model_activate(code: str, version: str, body: ModelAction, p: Principal = Depends(require("agents:manage")),
                      key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/ai/models/{code}/{version}/activate", key, body)
        if idem.replay:
            return idem.replay
        ml_registry.ensure_baselines(s)
        return idem.store(ml_registry.view(ml_registry.activate_version(s, code, version, body.reason)))


@router.post("/ai/models/{code}/{version}/suspend", tags=["AI"])
def ai_model_suspend(code: str, version: str, body: ModelAction, p: Principal = Depends(require("agents:manage")),
                     key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/ai/models/{code}/{version}/suspend", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(ml_registry.suspend(s, code, version, body.reason))


class TrainIn(BaseModel):
    models: list[str] = Field(default_factory=lambda: ["demand_forecast", "late_delivery", "invoice_exception_cause"])
    activate: bool = True
    shouldCost: list[str] = Field(default_factory=list)


@router.post("/ai/models/train", tags=["AI"])
def ai_train(body: TrainIn, p: Principal = Depends(require("agents:manage")), key: Optional[str] = Depends(idempotency_key)):
    """Train from the tenant's data and register (same as ``python -m app.pic.tools.ai_train``; the duplicate scorer is trained by the CLI)."""
    from app.pic.tools import ai_train as trainer
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/ai/models/train", key, body)
        if idem.replay:
            return idem.replay
        ml_registry.ensure_baselines(s)
        out = {}
        for name in body.models:
            if name == "demand_forecast":
                out[name] = ml_models.train_demand(s, body.activate)
            elif name == "late_delivery":
                out[name] = ml_models.train_late_delivery(s, activate=body.activate)
            elif name == "invoice_exception_cause":
                out[name] = ml_models.train_exception_cause(s, body.activate)
            elif name == "price_trend":
                out[name] = trainer.train_price_trend(s, body.activate)
            else:
                raise Problem(422, "UNKNOWN_MODEL", f"{name} is not trainable here; use one of demand_forecast, late_delivery, invoice_exception_cause, price_trend")
        for commodity in body.shouldCost:
            if commodity.upper() not in ml_models.COMMODITIES:
                raise Problem(422, "UNKNOWN_COMMODITY", f"commodity must be one of {', '.join(ml_models.COMMODITIES)}")
            out[f"should_cost_{commodity.lower()}"] = ml_models.train_should_cost(s, commodity.upper(), activate=body.activate)
        return idem.store(out)


@router.post("/ai/models/{code}/drift-check", tags=["AI"])
def ai_drift_check(code: str, p: Principal = Depends(require("agents:manage")), key: Optional[str] = Depends(idempotency_key)):
    """Compare the live feature distributions (PSI) and accuracy with the active version's training baseline; an alert suspends the
    version and re-activates the previous one."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/ai/models/{code}/drift-check", key, {})
        if idem.replay:
            return idem.replay
        if code == ml_models.LATE:
            inputs = ml_models.late_drift_inputs(s)
            return idem.store(ml_registry.check_drift(s, code, features=inputs["features"]))
        return idem.store(ml_registry.check_drift(s, code))


@router.post("/ai/late-delivery/refresh", tags=["AI"])
def ai_refresh_late_delivery(p: Principal = Depends(require("supplier:manage")), key: Optional[str] = Depends(idempotency_key)):
    """Replace the seeded twin late-delivery probability by the active model's (only when a trained model is active)."""
    with uow(p) as s:
        idem = idempotent(s, "POST /v1/ai/late-delivery/refresh", key, {})
        if idem.replay:
            return idem.replay
        return idem.store(ml_models.refresh_twin_late_delivery(s))


@router.get("/ai/price-trend", tags=["AI"])
def ai_price_trend(material: str, horizon: int = Query(3, ge=1, le=12), p: Principal = Depends(require(READ))):
    with uow(p) as s:
        return ml_models.price_trend(ml_models.price_history(s, material), horizon)


@router.get("/ai/invoice-exceptions/{exception_id}/cause", tags=["AI"])
def ai_exception_cause(exception_id: uuid.UUID, p: Principal = Depends(require_any("invoice:resolve", "invoice:approve"))):
    with uow(p) as s:
        exc = s.get(InvoiceException, exception_id)
        if exc is None:
            raise not_found("Invoice exception", exception_id)
        return ml_models.classify_exception(s, exc)


class ShouldCostIn(BaseModel):
    commodity: str
    params: dict


@router.post("/ai/should-cost", tags=["AI"])
def ai_should_cost(body: ShouldCostIn, p: Principal = Depends(require_any("sourcing:manage", "savings:manage"))):
    commodity = body.commodity.upper()
    if commodity not in ml_models.COMMODITIES:
        raise Problem(422, "UNKNOWN_COMMODITY", f"commodity must be one of {', '.join(ml_models.COMMODITIES)}")
    with uow(p) as s:
        try:
            return ml_models.should_cost(commodity, body.params, ml_models.active_calibration(s, commodity))
        except ValueError as exc:
            raise Problem(422, "INVALID_PARAMETERS", str(exc))


class DuplicateIn(BaseModel):
    nameA: str = Field(min_length=2, max_length=200)
    nameB: str = Field(min_length=2, max_length=200)
    panA: Optional[str] = Field(default=None, max_length=10)
    panB: Optional[str] = Field(default=None, max_length=10)
    gstinA: Optional[str] = Field(default=None, max_length=15)
    gstinB: Optional[str] = Field(default=None, max_length=15)


@router.post("/ai/duplicate-score", tags=["AI"])
def ai_duplicate_score(body: DuplicateIn, p: Principal = Depends(require_any("supplier:manage", "mdm:request"))):
    return ml_models.duplicate_score(body.nameA, body.nameB, pan_a=body.panA, pan_b=body.panB, gstin_a=body.gstinA, gstin_b=body.gstinB)


class RedlineSuggestIn(BaseModel):
    proposedText: Optional[str] = Field(default=None, max_length=4000)


@router.post("/contracts/{ref}/clauses/{clause}/redline-suggestion", tags=["AI"])
def contract_redline_suggestion(ref: str, clause: str, body: RedlineSuggestIn, p: Principal = Depends(require("contract:manage")),
                                key: Optional[str] = Depends(idempotency_key)):
    """Suggested counter wording from the CLM playbook (retrieval), drafted by the LLM gateway when configured. Nothing is changed."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/contracts/{ref}/clauses/{clause}/redline-suggestion", key, body)
        if idem.replay:
            return idem.replay
        return idem.store(ai_assist.suggest_redline(s, by_ref(s, Contract, ref), clause, body.proposedText))
