"""D9 AI evaluation sets: labelled spend lines, forecast actuals, duplicate pairs, Copilot questions (TD §17).

The sets are versioned files under ``backend/data/eval`` (see ``app.pic.tools.ai_eval``): the labelled spend lines and the
forecast holdout are exported from the seeded ERP history of AXN, the curated spend texts, supplier duplicate pairs and
Copilot questions are hand-labelled. The pack checks that the database-derived sets still match the tenant (integrity),
runs every evaluation against the platform's own services in transactions that roll back (spend.classify_text,
forecasting.generate and spend.forecast, supplier.screen and spend.suppliers_view, copilot.ask), and records the results in
the audit trail: one AI_EVALUATION event with the full metrics and an EVALUATED event on each evaluated agent
(SPEND_CLASSIFICATION, DEMAND_SENSING, COPILOT), which is the evidence the autonomy gate of TD §17 asks for before an agent's
autonomy level is raised. Nothing else is written. Evaluated as of 1 July 2027 (after the AXN dataset windows).
"""
import uuid
from datetime import date

from sqlalchemy import select

from app.pic.models import Agent
from app.pic.platform import audit
from app.pic.seed.axion import at

KEY = "ai-evaluation-sets"
VERSION = "1"
TITLE = "D9 AI evaluation sets: labelled spend lines, forecast actuals, duplicate pairs, Copilot questions"
TENANTS = ('AXN',)
CREATES_TENANT = False
READY = True

NS = uuid.UUID("0b8f7a52-6c0e-4d8e-9a43-5f2f3c9e1d17")
RECORDED_AT = (date(2027, 7, 1), 9)
AGENT_SETS = {"SPEND_CLASSIFICATION": "classification", "DEMAND_SENSING": "forecast", "COPILOT": "copilot"}


def _agent_metrics(report: dict, agent: str) -> dict:
    if agent == "SPEND_CLASSIFICATION":
        c = report["classification"]
        return {"accuracy": c["accuracy"], "lines": c["lines"], "threshold": c["threshold"],
                "erpHistoryAccuracy": c["erpHistory"]["accuracy"], "curatedAccuracy": c["curated"]["accuracy"],
                "autoApplyPrecision": c["curated"]["autoApplyPrecision"], "reviewRate": c["curated"]["reviewRate"]}
    if agent == "DEMAND_SENSING":
        f = report["forecast"]
        return {"mapeH1": f["mapeH1"], "mapeByHorizon": f["mapeByHorizon"], "erpPlanMapeH1": f["erpPlanMapeH1"], "points": f["points"],
                "spendForecastMape": f["spendForecast"]["mape"]}
    q = report["copilot"]
    return {"completeness": q["completeness"], "gate": q["gate"], "routingAccuracy": q["routingAccuracy"],
            "evidenceAccuracy": q["evidenceAccuracy"], "questions": q["questions"]}


def apply(tenant_code: str, password: str) -> dict:
    from app.pic.tools import ai_eval

    report = ai_eval.evaluate(tenant_code)
    integrity = report["classification"]["integrityErrors"] + report["forecast"]["integrityErrors"] + report["dedup"]["missingSuppliers"]
    if integrity:
        raise RuntimeError(f"AI evaluation sets do not match tenant {tenant_code}: {integrity[:5]} (re-export with --build-sets)")
    sc = ai_eval.scenario(tenant_code)
    gates = report["gates"]
    with sc.act("admin", at(*RECORDED_AT)) as s:
        event = audit.record(s, "AI_EVALUATION", uuid.uuid5(NS, f"{tenant_code}:{VERSION}"), "EVALUATED", object_ref=f"D9 eval sets v{VERSION}",
                             after={k: report[k] for k in ("classification", "forecast", "dedup", "copilot", "gates")},
                             reason="TD §17 offline evaluation before autonomy level increases")
        for code, name in AGENT_SETS.items():
            agent = s.execute(select(Agent).where(Agent.code == code)).scalar_one_or_none()
            if agent is not None:
                audit.record(s, "AGENT", agent.id, "EVALUATED", object_ref=code, ai_ref=str(event.event_id),
                             after={"set": name, "autonomyLevel": agent.autonomy_level, "modelVersion": agent.model_version,
                                    **_agent_metrics(report, code)})
    c, f, d, q = report["classification"], report["forecast"], report["dedup"], report["copilot"]
    failed = [k for k, g in gates.items() if not g["pass"]]
    return {"notes": ai_eval.summary_lines(report)
            + ([f"Below proposed target (review before raising autonomy): {', '.join(failed)}"] if failed else []),
            "counts": {"labelledSpendLines": c["lines"], "erpHistoryLines": c["erpHistory"]["lines"], "curatedLines": c["curated"]["lines"],
                       "forecastPoints": f["points"], "dedupPairs": d["pairs"], "copilotQuestions": q["questions"],
                       "auditEvents": 1 + len(AGENT_SETS)},
            "metrics": {"classificationAccuracy": c["accuracy"], "curatedAccuracy": c["curated"]["accuracy"], "forecastMapeH1": f["mapeH1"],
                        "spendForecastMape": f["spendForecast"]["mape"], "dedupF8": [d["F8_SCREENING"]["precision"], d["F8_SCREENING"]["recall"]],
                        "dedupSpd": [d["SPD_CLUSTERS"]["precision"], d["SPD_CLUSTERS"]["recall"]], "copilotCompleteness": q["completeness"]}}
