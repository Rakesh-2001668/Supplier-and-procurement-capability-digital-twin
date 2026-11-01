"""Train, evaluate and register the platform's light ML models for a tenant (Technical Document §13).

    python -m app.pic.tools.ai_train --tenant AXN                       # every model that has enough data
    python -m app.pic.tools.ai_train --tenant AXN --model late_delivery --no-activate
    python -m app.pic.tools.ai_train --tenant AXN --should-cost FORGING

Models: demand_forecast, late_delivery, price_trend, invoice_exception_cause, supplier_dedup, should_cost (needs --should-cost
COMMODITY: FORGING or PLASTIC_MOULDING, calibrated on the tenant's priced materials). Training is deterministic: the same data
gives the same parameters and the same ``dataHash``. Each run stores the model version with its metrics in the registry
(``ml_model``, ``ml_eval_run``); a version becomes ACTIVE only when its gate passes (``--no-activate`` keeps it a CANDIDATE).
The database is DATABASE_URL (or --database-url).
"""
import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass

MODELS = ("demand_forecast", "late_delivery", "price_trend", "invoice_exception_cause", "supplier_dedup")


def _principal(tenant_id, code):
    from app.pic.platform.auth import Principal

    @dataclass
    class TrainPrincipal(Principal):
        @property
        def actor(self) -> str:
            return "integration:ai_train"

    return TrainPrincipal(user_id=uuid.UUID(int=0), tenant_id=tenant_id, tenant_code=code, email="ai.train", name="AI training", roles=[], scopes=set())


def train_price_trend(session, activate: bool = True) -> dict:
    from sqlalchemy import select

    from app.pic.models import Material
    from app.pic.services import ml_models, ml_registry

    series = []
    for number in session.execute(select(Material.number)).scalars():
        history = ml_models.price_history(session, number)
        if len(history) >= 8:
            series.append([v for _, v in history])
    metrics = ml_models.evaluate_price_trend(series)
    if not metrics["points"]:
        return {"trained": False, "reason": "no material has 8 months of purchase prices", "series": len(series)}
    model = ml_registry.register(session, code=ml_models.TREND, version=ml_models.TREND_VERSION, kind="STATISTICAL",
                                 params={"phi": 0.95, "alphas": [0.2, 0.4, 0.6, 0.8], "betas": [0.05, 0.1, 0.2, 0.3]}, metrics={"rolling": metrics},
                                 training={"series": len(series), "points": metrics["points"], "dataHash": ml_models._hash(series)},
                                 description="Holt exponential smoothing with damped trend per material")
    gate = metrics["mape"] is not None and metrics["mapeLastPrice"] is not None and metrics["mape"] <= metrics["mapeLastPrice"] + 1e-9
    ml_registry.record_eval(session, code=ml_models.TREND, version=ml_models.TREND_VERSION, dataset="tenant rolling origin", metrics=metrics, gate=gate)
    if activate and gate:
        ml_registry.ensure_baselines(session)
        ml_registry.activate_version(session, ml_models.TREND, ml_models.TREND_VERSION, "one-step error not above the last-price forecast")
    return {"trained": True, "model": ml_registry.view(model), "metrics": metrics, "activated": bool(activate and gate)}


def train_dedup(session, tenant_code: str, activate: bool = True) -> dict:
    """Register the embedding duplicate scorer with the D9 pair metrics (AXN holds the labelled pairs' counterparts)."""
    from app.pic.services import ml_models, ml_registry
    from app.pic.tools import ai_eval

    if tenant_code != "AXN":
        return {"trained": False, "reason": "the labelled duplicate pairs (D9) refer to the AXN demo tenant"}
    report = ai_eval.evaluate(tenant_code, ["dedup"])["dedup"]
    base, emb = report["EITHER"], report["EMBEDDING"]
    metrics = {"pairs": report["pairs"], "baseline": {k: base[k] for k in ("precision", "recall")}, "embedding": {k: emb[k] for k in ("precision", "recall", "tp", "fp", "fn")}}
    model = ml_registry.register(
        session, code=ml_models.DEDUP, version=ml_models.DEDUP_VERSION, kind="EMBEDDING",
        params={"dim": 512, "ngrams": [2, 3, 4], "weights": {"cosine": 0.6, "ratio": 0.4}, "duplicateAt": ml_models.DEDUP_COSINE, "reviewAt": ml_models.DEDUP_REVIEW,
                "rules": ["same GSTIN", "same PAN", "different PAN = distinct"]},
        metrics={"d9": metrics}, training={"pairs": report["pairs"], "label": "D9 supplier_dedup_pairs.csv"},
        description="Character n-gram hashing embedding (cosine) + name ratio with PAN / GSTIN rules")
    gate = emb["recall"] is not None and emb["recall"] >= (base["recall"] or 0) and (emb["precision"] or 0) >= (base["precision"] or 0)
    ml_registry.record_eval(session, code=ml_models.DEDUP, version=ml_models.DEDUP_VERSION, dataset="D9 supplier_dedup_pairs", metrics=metrics, gate=gate)
    if activate and gate:
        ml_registry.ensure_baselines(session)
        ml_registry.activate_version(session, ml_models.DEDUP, ml_models.DEDUP_VERSION, "recall kept and precision not lower than F8-03 + SPD-03")
    return {"trained": True, "model": ml_registry.view(model), "metrics": metrics, "activated": bool(activate and gate)}


def train(tenant_code: str, models=None, *, activate: bool = True, should_cost: list = None) -> dict:
    from sqlalchemy import select

    from app.pic.db import system_tx, tenant_tx
    from app.pic.models import Tenant
    from app.pic.services import ml_models, ml_registry

    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == tenant_code)).scalar_one()
    chosen = list(models or MODELS)
    out = {}
    principal = _principal(tenant_id, tenant_code)
    for name in chosen:
        if name == "supplier_dedup":
            # the evaluation opens its own rolled-back transactions; register in a separate one
            with tenant_tx(tenant_id, principal.user_id, principal) as s:
                out[name] = train_dedup(s, tenant_code, activate)
            continue
        with tenant_tx(tenant_id, principal.user_id, principal) as s:
            ml_registry.ensure_baselines(s)
            if name == "demand_forecast":
                out[name] = ml_models.train_demand(s, activate)
            elif name == "late_delivery":
                out[name] = ml_models.train_late_delivery(s, activate=activate)
            elif name == "invoice_exception_cause":
                out[name] = ml_models.train_exception_cause(s, activate)
            elif name == "price_trend":
                out[name] = train_price_trend(s, activate)
            else:
                raise SystemExit(f"unknown model {name}; known: {', '.join(MODELS)}")
    for commodity in should_cost or []:
        with tenant_tx(tenant_id, principal.user_id, principal) as s:
            out[f"should_cost_{commodity.lower()}"] = ml_models.train_should_cost(s, commodity.upper(), activate=activate)
    return out


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m app.pic.tools.ai_train", description=__doc__.split("\n")[0])
    ap.add_argument("--tenant", default="AXN")
    ap.add_argument("--model", action="append", choices=MODELS, dest="models")
    ap.add_argument("--should-cost", action="append", choices=("FORGING", "PLASTIC_MOULDING"), dest="should_cost")
    ap.add_argument("--no-activate", action="store_true", help="register as CANDIDATE even when the gate passes")
    ap.add_argument("--database-url")
    args = ap.parse_args(argv)
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    import app.pic.services  # noqa: F401
    result = train(args.tenant, args.models if args.models or args.should_cost is None else [], activate=not args.no_activate, should_cost=args.should_cost)
    print(json.dumps(result, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
