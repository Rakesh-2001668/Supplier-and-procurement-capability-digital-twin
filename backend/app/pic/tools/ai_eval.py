"""AI evaluation sets and evaluator (D9, Technical Document §17: "AI evaluation — classification accuracy, forecast MAPE,
answer-contract completeness — offline eval sets + human review — gate: before autonomy level increases").

    python -m app.pic.tools.ai_eval                       # evaluate every set against tenant AXN, print a report
    python -m app.pic.tools.ai_eval --set classification --json
    python -m app.pic.tools.ai_eval --build-sets          # (re)export the ERP-history and forecast sets from a seeded database

The database is DATABASE_URL (as for the API). Evaluation is read-only: every set runs inside a transaction that is rolled
back (forecast origins re-run forecasting.generate with the clock pinned; the dedup pairs register their synthetic suppliers
and run the F8-03 screening there), so it is safe on any environment. --build-sets only reads the database and writes the
files under backend/data/eval.

Sets (backend/data/eval):
- spend_erp_history.csv  every spend line of the seeded ERP history with its ERP category as ground truth (lines that came
                         without a category carry the steward-confirmed category); spend_curated.csv hand-labelled texts.
                         → spend.classify_text (keyword evidence + supplier prior) → accuracy, auto-apply precision, review rate.
- forecast_holdout.csv   ERP consumption actuals of the last six months: rolling-origin re-forecast with forecasting.generate
                         (exponential smoothing, rule DEMAND-SENSING) → MAPE by horizon, compared with the ERP plan; plus the
                         SPD-09 spend forecast (spend.forecast, Holt) against the last three months of ERP spend per category.
- supplier_dedup_pairs.csv  labelled DUPLICATE / DISTINCT pairs → precision / recall of supplier.screen (F8-03) and of the
                         spend.suppliers_view duplicate clusters (SPD-03).
- copilot_questions.json questions per user with the expected route and evidence → copilot.ask → answer-contract completeness
                         (gate ≥ 99 %), routing and evidence accuracy, document-status correctness.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parents[3]
EVAL_DIR = BACKEND_DIR / "data" / "eval"
SETS = ("classification", "forecast", "dedup", "copilot")
HOLDOUT_PERIODS = 6
SPEND_HOLDOUT_ORIGIN = "2026-07"  # SPD-09 spend forecast: history up to June 2026, forecast July–September 2026 (ERP history)
CONTRACT_FIELDS = ("answer", "evidence", "confidence", "explanation", "recommendedAction", "permission")
INTENTS = [  # explanation.method → route
    ("document lookup + workflow history", "DOCUMENT"), ("document lookup", "DOCUMENT_NOT_FOUND"), ("task inbox", "TASKS"),
    ("spend cube", "SPEND"), ("permission check", "PERMISSION_DENIED"), ("savings", "SAVINGS"), ("invoice exception", "EXCEPTIONS"),
    ("KPI aggregation", "KPI"), ("supplier 360", "SUPPLIER"), ("supplier users are limited", "SUPPLIER_SCOPE"), ("no match", "NO_MATCH"),
]
# Proposed gates (only the Copilot completeness gate is documented: TD §17 / Remaining Work Report D9); confirm before use.
GATES = {"classificationAccuracy": 0.90, "autoApplyPrecision": 0.95, "forecastMapeH1": 0.15, "dedupPrecision": 0.90,
         "dedupRecall": 0.80, "copilotCompleteness": 0.99}


class _Rollback(Exception):
    pass


# ---------------------------------------------------------------- files
def read_csv(name: str) -> tuple[list[str], list[dict]]:
    text = (EVAL_DIR / name).read_text(encoding="utf-8")
    header = [line[1:].strip() for line in text.splitlines() if line.startswith("#")]
    return header, list(csv.DictReader(io.StringIO("\n".join(l for l in text.splitlines() if not l.startswith("#")))))


def write_csv(name: str, header: list[str], fields: list[str], rows: list[dict]) -> Path:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    for line in header:
        buf.write(f"# {line}\n")
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path = EVAL_DIR / name
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


def copilot_set() -> dict:
    return json.loads((EVAL_DIR / "copilot_questions.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- sessions
def scenario(tenant_code: str):
    from sqlalchemy import select

    from app.pic.db import system_tx, tenant_tx
    from app.pic.models import AppUser, Tenant
    from app.pic.seed.axion import Scenario

    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == tenant_code)).scalar_one()
    with tenant_tx(tenant_id) as s:
        emails = [u.email for u in s.execute(select(AppUser).where(AppUser.supplier_id.is_(None))).scalars() if "TENANT_ADMIN" in u.roles]
    domain = emails[0].split("@", 1)[1] if emails else "axion.example"
    return Scenario(tenant_id, tenant_code, domain)


@contextmanager
def rolled_back(sc, who: str, when: datetime):
    """A tenant transaction acting as `who` at `when` that is always rolled back."""
    from app.pic.platform import clock
    try:
        with sc.act(who, when) as s:
            yield s
            raise _Rollback
    except _Rollback:
        pass
    finally:
        clock.set_pinned(None)


def _when(day: date, hour: int = 9) -> datetime:
    from app.pic.platform import clock
    return clock.at_ist(day, hour)


def _ratio(num: int, den: int) -> Optional[float]:
    return round(num / den, 4) if den else None


# ---------------------------------------------------------------- build the database-derived sets
def build_sets(tenant_code: str = "AXN") -> dict:
    """Export the ERP-history labelled lines and the forecast holdout from a database seeded with the signature case."""
    from sqlalchemy import select

    from app.pic.db import tenant_tx
    from app.pic.models import Forecast, Material, SpendLine, Supplier
    from app.pic.seed import intelligence

    sc = scenario(tenant_code)
    truth_by_text = {t: c for c, t in intelligence.UNCLASSIFIED_TEXTS}
    with tenant_tx(sc.tenant_id) as s:
        codes = {sid: code for sid, code in s.execute(select(Supplier.id, Supplier.code))}
        lines = s.execute(select(SpendLine).where(SpendLine.source == "ERP_HISTORY").order_by(SpendLine.invoice_ref)).scalars().all()
        spend_rows = []
        for line in lines:
            truth = truth_by_text.get(line.description) if line.material_group == "MISC" else line.material_group
            if truth is None:
                continue
            spend_rows.append({"ref": line.invoice_ref, "period": line.period, "supplier_code": codes.get(line.supplier_id, ""),
                               "material_group": line.material_group, "description": line.description, "truth_category": truth})
        forecast_rows = []
        for material in s.execute(select(Material).order_by(Material.number)).scalars():
            history = s.execute(select(Forecast).where(Forecast.material_id == material.id, Forecast.actual_qty.is_not(None),
                                                      Forecast.actual_source == "ERP_CONSUMPTION_HISTORY")
                                .order_by(Forecast.plant, Forecast.period)).scalars().all()
            by_plant = defaultdict(list)
            for f in history:
                by_plant[f.plant].append(f)
            for plant, rows in by_plant.items():
                for f in rows[-HOLDOUT_PERIODS:]:
                    forecast_rows.append({"material": material.number, "plant": plant, "period": f.period,
                                          "actual_qty": format(f.actual_qty.normalize(), "f"),
                                          "erp_plan_qty": format(f.statistical_qty.normalize(), "f") if f.method == "ERP_PLAN" else ""})
    a = write_csv("spend_erp_history.csv", [
        "Labelled spend lines from the seeded ERP history (D9): every ERP_HISTORY spend line of tenant AXN (signature-case seed,",
        "seed/intelligence.py, SAP initial load Oct 2024 - Sep 2026). truth_category = the category of the ERP material group; lines",
        "that arrived without a category (material group MISC) carry the category a steward confirms for that text.",
        f"Exported by python -m app.pic.tools.ai_eval --build-sets on {date.today().isoformat()}; {len(spend_rows)} lines.",
    ], ["ref", "period", "supplier_code", "material_group", "description", "truth_category"], spend_rows)
    b = write_csv("forecast_holdout.csv", [
        f"Forecast holdout (D9): the last {HOLDOUT_PERIODS} months of ERP consumption actuals per material and plant (ERP stock feed loaded",
        "by the signature case) with the ERP plan for the same month. The evaluator re-runs forecasting.generate at each holdout month",
        "(clock pinned, actuals from that month on hidden by the service's own cut-off) and scores horizons 1-3 with MAPE.",
        f"Exported by python -m app.pic.tools.ai_eval --build-sets on {date.today().isoformat()}.",
    ], ["material", "plant", "period", "actual_qty", "erp_plan_qty"], forecast_rows)
    return {"spendErpHistory": str(a), "lines": len(spend_rows), "forecastHoldout": str(b), "points": len(forecast_rows)}


# ---------------------------------------------------------------- classification
def evaluate_classification(sc) -> dict:
    from sqlalchemy import select

    from app.pic.models import SpendLine, Supplier
    from app.pic.platform import rules
    from app.pic.services import spend

    _, erp = read_csv("spend_erp_history.csv")
    _, curated = read_csv("spend_curated.csv")
    out = {}
    with rolled_back(sc, "category.head", _when(date(2027, 3, 31))) as s:
        threshold = Decimal(str(rules.resolve(s, "SPEND-GOVERNANCE").body["classificationThreshold"]))
        suppliers = {code: sid for sid, code in s.execute(select(Supplier.id, Supplier.code))}
        nodes = spend._nodes(s)
        known = {n.code for n in nodes}
        # Integrity: every ERP-history line of the set exists in the tenant with the same text.
        seeded = dict(s.execute(select(SpendLine.invoice_ref, SpendLine.description).where(SpendLine.source == "ERP_HISTORY")).all())
        integrity = [r["ref"] for r in erp if seeded.get(r["ref"]) != r["description"]]
        for name, rows in (("erpHistory", erp), ("curated", curated)):
            total = correct = auto = auto_correct = 0
            per_cat = defaultdict(lambda: {"lines": 0, "correct": 0, "predicted": 0})
            errors = Counter()
            texts, texts_ok = set(), set()
            for row in rows:
                sid = suppliers.get(row.get("supplier_code") or "")
                category, confidence, _ = spend.classify_text(s, row["description"], sid, nodes)
                truth = row["truth_category"]
                ok = category == truth
                total += 1
                correct += ok
                per_cat[truth]["lines"] += 1
                per_cat[truth]["correct"] += ok
                per_cat[category]["predicted"] += 1
                if confidence >= threshold:
                    auto += 1
                    auto_correct += ok
                if not ok:
                    errors[(row["description"][:70], truth, category)] += 1
                texts.add(row["description"])
                if ok:
                    texts_ok.add(row["description"])
            out[name] = {
                "lines": total, "accuracy": _ratio(correct, total), "autoApplied": auto, "autoApplyRate": _ratio(auto, total),
                "autoApplyPrecision": _ratio(auto_correct, auto), "reviewRate": _ratio(total - auto, total),
                "distinctTexts": len(texts), "distinctTextAccuracy": _ratio(len(texts_ok), len(texts)),
                "perCategory": {c: {"lines": v["lines"], "recall": _ratio(v["correct"], v["lines"]), "precision": _ratio(v["correct"], v["predicted"])}
                                for c, v in sorted(per_cat.items()) if v["lines"] or v["predicted"]},
                "topErrors": [{"text": t, "truth": tr, "predicted": p, "lines": n} for (t, tr, p), n in errors.most_common(12)],
                "unknownTruthCategories": sorted({r["truth_category"] for r in rows} - known),
            }
    all_lines = out["erpHistory"]["lines"] + out["curated"]["lines"]
    all_correct = sum(round(out[k]["accuracy"] * out[k]["lines"]) for k in ("erpHistory", "curated") if out[k]["lines"])
    out.update(model="spend.classify_text (keywords + supplier prior)", threshold=str(threshold), integrityErrors=integrity[:20],
               accuracy=_ratio(all_correct, all_lines), lines=all_lines)
    return out


# ---------------------------------------------------------------- forecasting
def _shift(period: str, months: int) -> str:
    y, m = int(period[:4]), int(period[5:]) + months
    while m > 12:
        y, m = y + 1, m - 12
    return f"{y:04d}-{m:02d}"


def evaluate_forecast(sc) -> dict:
    from sqlalchemy import select

    from app.pic.models import Forecast, Material
    from app.pic.services import forecasting

    _, rows = read_csv("forecast_holdout.csv")
    actual = {(r["material"], r["plant"], r["period"]): Decimal(r["actual_qty"]) for r in rows}
    plan = {(r["material"], r["plant"], r["period"]): Decimal(r["erp_plan_qty"]) for r in rows if r["erp_plan_qty"]}
    origins = sorted({r["period"] for r in rows})
    points, integrity = [], []
    for origin in origins:
        with rolled_back(sc, "mrp.controller", _when(date(int(origin[:4]), int(origin[5:]), 15))) as s:
            materials = {m.number: m.id for m in s.execute(select(Material)).scalars()}
            if origin == origins[0]:
                for (number, plant, period), qty in actual.items():
                    db = s.execute(select(Forecast.actual_qty).where(Forecast.material_id == materials.get(number), Forecast.plant == plant,
                                                                     Forecast.period == period)).scalar()
                    if db is None or Decimal(db) != qty:
                        integrity.append(f"{number}/{plant}/{period}: file {qty}, database {db}")
            forecasting.generate(s, horizon=3)
            s.flush()
            for (number, plant) in sorted({(k[0], k[1]) for k in actual}):
                for h in range(3):
                    period = _shift(origin, h)
                    if (number, plant, period) not in actual:
                        continue
                    f = s.execute(select(Forecast).where(Forecast.material_id == materials[number], Forecast.plant == plant,
                                                         Forecast.period == period)).scalar_one()
                    points.append({"material": number, "plant": plant, "origin": origin, "period": period, "horizon": h + 1,
                                   "forecast": Decimal(f.statistical_qty), "actual": actual[(number, plant, period)],
                                   "erpPlan": plan.get((number, plant, period))})

    def mape(items, key="forecast"):
        items = [p for p in items if p[key] is not None and p["actual"]]
        return round(float(sum(abs(p[key] - p["actual"]) / p["actual"] for p in items) / len(items)), 4) if items else None

    by_material = {m: mape([p for p in points if p["material"] == m and p["horizon"] == 1]) for m in sorted({p["material"] for p in points})}
    h1 = [p for p in points if p["horizon"] == 1]
    return {"model": f"forecasting.generate ({forecasting.MODEL_VERSION}, rule DEMAND-SENSING)", "origins": origins, "points": len(points),
            "mapeH1": mape(h1), "mapeByHorizon": {h: mape([p for p in points if p["horizon"] == h]) for h in (1, 2, 3)},
            "mapeAll": mape(points), "erpPlanMapeH1": mape(h1, "erpPlan"), "mapeH1ByMaterial": by_material,
            "integrityErrors": integrity, "spendForecast": evaluate_spend_forecast(sc)}


def evaluate_spend_forecast(sc) -> dict:
    """SPD-09 spend forecast (Holt) with history up to the month before SPEND_HOLDOUT_ORIGIN, against the ERP spend actuals."""
    from sqlalchemy import func, select

    from app.pic.models import SpendLine
    from app.pic.services import spend

    origin = SPEND_HOLDOUT_ORIGIN
    with rolled_back(sc, "category.head", _when(date(int(origin[:4]), int(origin[5:]), 5))) as s:
        result = spend.forecast(s)
        periods = result["horizon"][:3]
        actual = defaultdict(int)
        for category, period, amount in s.execute(select(SpendLine.category, SpendLine.period, func.sum(SpendLine.amount_minor))
                                                  .where(SpendLine.period.in_(periods), SpendLine.source == "ERP_HISTORY")
                                                  .group_by(SpendLine.category, SpendLine.period)):
            actual[(category, period)] = int(amount)
    errors = []
    for series in result["series"]:
        for point in series["points"]:
            if "forecastMinor" in point and point["period"] in periods and actual.get((series["category"], point["period"])):
                a = actual[(series["category"], point["period"])]
                errors.append((series["category"], point["period"], abs(point["forecastMinor"] - a) / a,
                               point["lowMinor"] <= a <= point["highMinor"]))
    per_cat = defaultdict(list)
    for cat, _, err, _ in errors:
        per_cat[cat].append(err)
    return {"model": "spend.forecast (Holt linear, 80% band)", "history": result["history"], "holdout": periods, "points": len(errors),
            "mape": round(sum(e[2] for e in errors) / len(errors), 4) if errors else None,
            "bandCoverage": _ratio(sum(1 for e in errors if e[3]), len(errors)),
            "worstCategories": sorted(({"category": c, "mape": round(sum(v) / len(v), 4)} for c, v in per_cat.items()),
                                      key=lambda x: -x["mape"])[:5]}


# ---------------------------------------------------------------- supplier dedup
def evaluate_dedup(sc) -> dict:
    from sqlalchemy import select

    from app.pic.models import Supplier
    from app.pic.services import spend, supplier as supplier_svc
    from app.pic.services.master_changes import gstin_check_char

    _, pairs = read_csv("supplier_dedup_pairs.csv")
    predicted = {"F8_SCREENING": {}, "SPD_CLUSTERS": {}}
    missing = []
    with rolled_back(sc, "supplier.manager", _when(date(2027, 3, 31), 10)) as s:
        existing = {x.code: x for x in s.execute(select(Supplier)).scalars()}
        made = {}
        for pair in pairs:
            for side in ("a", "b"):
                code, name = pair[f"{side}_code"], pair[f"{side}_name"]
                if code in existing or code in made:
                    continue
                if not name:
                    missing.append(code)
                    continue
                gstin, pan = pair[f"{side}_gstin"], pair[f"{side}_pan"]
                if not gstin:  # registration needs well-formed tax IDs; synthetic ones, unmatched because their hashes are cleared below
                    pan = f"EVALX{int(hashlib.sha256(code.encode()).hexdigest(), 16) % 10_000:04d}Z"
                    gstin = f"33{pan}1Z" + gstin_check_char(f"33{pan}1Z")
                    name_only = True
                else:
                    name_only = False
                made[code] = supplier_svc.register(
                    s, code=code, legal_name=name, gstin=gstin, pan=pan,
                    state_code=gstin[:2], contact_email=f"{code.lower()}@eval.example", categories=[])
                if name_only:  # a name-only request: no tax identifiers to match on
                    made[code].gstin_hash = made[code].pan_hash = None
        s.flush()
        masters = {**existing, **made}
        for pair in pairs:
            if pair["a_code"] in missing or pair["b_code"] in missing:
                continue
            result = supplier_svc.screen(s, masters[pair["b_code"]], record_step=False)
            predicted["F8_SCREENING"][pair["pair_id"]] = pair["a_code"] in {d["code"] for d in result["duplicates"]}
        clusters = spend.suppliers_view(s)["duplicateClusters"]
        together = set()
        for cluster in clusters:
            codes = [x["code"] for x in cluster["suppliers"]]
            together |= {frozenset((a, b)) for a in codes for b in codes if a != b}
        for pair in pairs:
            if pair["pair_id"] in predicted["F8_SCREENING"]:
                predicted["SPD_CLUSTERS"][pair["pair_id"]] = frozenset((pair["a_code"], pair["b_code"])) in together
    labels = {p["pair_id"]: p["label"] == "DUPLICATE" for p in pairs}
    kinds = {p["pair_id"]: p["kind"] for p in pairs}
    predicted["EITHER"] = {k: predicted["F8_SCREENING"][k] or predicted["SPD_CLUSTERS"].get(k, False) for k in predicted["F8_SCREENING"]}
    out = {"pairs": len(labels), "duplicates": sum(labels.values()), "missingSuppliers": missing}
    for method, pred in predicted.items():
        tp = sum(1 for k, v in pred.items() if v and labels[k])
        fp = sum(1 for k, v in pred.items() if v and not labels[k])
        fn = sum(1 for k, v in pred.items() if not v and labels[k])
        tn = sum(1 for k, v in pred.items() if not v and not labels[k])
        precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
        out[method] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall,
                       "f1": round(2 * precision * recall / (precision + recall), 4) if precision and recall else None,
                       "missedKinds": dict(Counter(kinds[k] for k, v in pred.items() if not v and labels[k])),
                       "falseAlarmKinds": dict(Counter(kinds[k] for k, v in pred.items() if v and not labels[k])),
                       "falseAlarms": sorted(k for k, v in pred.items() if v and not labels[k]),
                       "missed": sorted(k for k, v in pred.items() if not v and labels[k])}
    return out


# ---------------------------------------------------------------- Copilot answer contract
def contract_problems(answer: dict) -> list[str]:
    problems = [f"missing {k}" for k in CONTRACT_FIELDS if k not in answer]
    if problems:
        return problems
    if not isinstance(answer["answer"], str) or not answer["answer"].strip():
        problems.append("answer empty")
    if not isinstance(answer["evidence"], list) or any(not isinstance(e, dict) or not {"type", "ref", "link"} <= set(e) for e in answer["evidence"]):
        problems.append("evidence malformed")
    c = answer["confidence"]
    if not isinstance(c, dict) or not isinstance(c.get("score"), (int, float)) or not 0 <= c["score"] <= 1 or c.get("label") not in ("high", "medium", "low"):
        problems.append("confidence malformed")
    e = answer["explanation"]
    if not isinstance(e, dict) or not all(e.get(k) for k in ("method", "modelVersion", "dataFreshness")):
        problems.append("explanation incomplete")
    a = answer["recommendedAction"]
    if a is not None and (not isinstance(a, dict) or not a.get("label") or not a.get("deepLink") or not isinstance(a.get("requiresHuman"), bool)):
        problems.append("recommendedAction malformed")
    p = answer["permission"]
    if not isinstance(p, dict) or p.get("autonomy") not in ("L0", "L1", "L2", "L3", "L4") or not isinstance(p.get("scopes"), list):
        problems.append("permission malformed")
    return problems


def intent_of(answer: dict) -> Optional[str]:
    method = ((answer.get("explanation") or {}).get("method") or "")
    return next((intent for marker, intent in INTENTS if marker in method), None)


def evaluate_copilot(sc) -> dict:
    from sqlalchemy import select

    from app.pic.models import Contract, Invoice, PurchaseOrder, Requisition, SourcingEvent
    from app.pic.services import copilot

    spec = copilot_set()
    models = {"PURCHASE_ORDER": PurchaseOrder, "REQUISITION": Requisition, "SOURCING_EVENT": SourcingEvent, "CONTRACT": Contract,
              "INVOICE": Invoice}
    results = []
    for q in spec["questions"]:
        with rolled_back(sc, q["user"], _when(date(2027, 3, 31), 16)) as s:
            answer = copilot.ask(s, s.info["principal"], q["question"])
            json.dumps(answer, default=str)  # the contract must serialise
            expected_status = None
            ev = q.get("evidence") or {}
            if q.get("documentStatus") and ev.get("type") in models:
                obj = s.execute(select(models[ev["type"]]).where(models[ev["type"]].number == ev["ref"])).scalar_one_or_none()
                expected_status = obj.status.replace("_", " ").lower() if obj else None
        problems = contract_problems(answer)
        intent = intent_of(answer)
        evidence_ok = True
        if ev:
            evidence_ok = any(e.get("type") == ev.get("type") and (not ev.get("ref") or e.get("ref") == ev["ref"]) for e in answer.get("evidence") or [])
        status_ok = None
        if q.get("documentStatus"):
            status_ok = bool(expected_status) and f" is {expected_status}." in answer.get("answer", "")
        results.append({"id": q["id"], "user": q["user"], "question": q["question"], "complete": not problems, "problems": problems,
                        "intent": intent, "expectedIntent": q["intent"], "routed": intent == q["intent"], "evidenceOk": evidence_ok,
                        "statusOk": status_ok, "answer": answer.get("answer", "")[:200]})
    n = len(results)
    status = [r for r in results if r["statusOk"] is not None]
    return {"model": "copilot.ask (copilot-rules-v1)", "questions": n, "completeness": _ratio(sum(r["complete"] for r in results), n),
            "gate": spec.get("gate", {}).get("completeness"), "routingAccuracy": _ratio(sum(r["routed"] for r in results), n),
            "evidenceAccuracy": _ratio(sum(r["evidenceOk"] for r in results), n),
            "documentStatusAccuracy": _ratio(sum(bool(r["statusOk"]) for r in status), len(status)),
            "failures": [r for r in results if not (r["complete"] and r["routed"] and r["evidenceOk"] and r["statusOk"] is not False)]}


# ---------------------------------------------------------------- orchestration and report
def evaluate(tenant_code: str = "AXN", sets: Optional[list[str]] = None) -> dict:
    sc = scenario(tenant_code)
    chosen = sets or list(SETS)
    report = {"tenant": tenant_code, "evaluatedAt": datetime.now().astimezone().isoformat(timespec="seconds"), "sets": chosen}
    runners = {"classification": evaluate_classification, "forecast": evaluate_forecast, "dedup": evaluate_dedup, "copilot": evaluate_copilot}
    for name in chosen:
        report[name] = runners[name](sc)
    report["gates"] = gate_results(report)
    return report


def gate_results(report: dict) -> dict:
    values = {
        "classificationAccuracy": (report.get("classification") or {}).get("accuracy"),
        "autoApplyPrecision": ((report.get("classification") or {}).get("curated") or {}).get("autoApplyPrecision"),
        "forecastMapeH1": (report.get("forecast") or {}).get("mapeH1"),
        "dedupPrecision": ((report.get("dedup") or {}).get("EITHER") or {}).get("precision"),
        "dedupRecall": ((report.get("dedup") or {}).get("EITHER") or {}).get("recall"),
        "copilotCompleteness": (report.get("copilot") or {}).get("completeness"),
    }
    out = {}
    for key, value in values.items():
        if value is None:
            continue
        target = GATES[key]
        passed = value <= target if key == "forecastMapeH1" else value >= target
        out[key] = {"value": value, "target": target, "pass": passed, "documented": key == "copilotCompleteness"}
    return out


def summary_lines(report: dict) -> list[str]:
    lines = []
    c = report.get("classification")
    if c:
        lines.append(f"Classification ({c['lines']} lines, threshold {c['threshold']}): accuracy {c['accuracy']}; ERP history "
                     f"{c['erpHistory']['accuracy']} (auto-applied {c['erpHistory']['autoApplyRate']}, precision {c['erpHistory']['autoApplyPrecision']}); "
                     f"curated {c['curated']['accuracy']} (auto-applied {c['curated']['autoApplyRate']}, precision {c['curated']['autoApplyPrecision']})")
    f = report.get("forecast")
    if f:
        sf = f["spendForecast"]
        lines.append(f"Demand forecast ({f['points']} points, origins {f['origins'][0]}–{f['origins'][-1]}): MAPE h1 {f['mapeH1']}, "
                     f"by horizon {f['mapeByHorizon']}, ERP plan h1 {f['erpPlanMapeH1']}; spend forecast {sf['holdout'][0]}–{sf['holdout'][-1]}: "
                     f"MAPE {sf['mape']}, 80% band coverage {sf['bandCoverage']}")
    d = report.get("dedup")
    if d:
        lines.append(f"Supplier dedup ({d['pairs']} pairs, {d['duplicates']} duplicates): F8 screening P {d['F8_SCREENING']['precision']} "
                     f"R {d['F8_SCREENING']['recall']}; SPD clusters P {d['SPD_CLUSTERS']['precision']} R {d['SPD_CLUSTERS']['recall']}; "
                     f"either P {d['EITHER']['precision']} R {d['EITHER']['recall']}")
    q = report.get("copilot")
    if q:
        lines.append(f"Copilot ({q['questions']} questions): contract completeness {q['completeness']} (gate {q['gate']}), routing "
                     f"{q['routingAccuracy']}, evidence {q['evidenceAccuracy']}, document status {q['documentStatusAccuracy']}")
    for key, g in report.get("gates", {}).items():
        lines.append(f"  gate {key}: {g['value']} vs {'≤' if key == 'forecastMapeH1' else '≥'} {g['target']} "
                     f"{'PASS' if g['pass'] else 'FAIL'}{'' if g['documented'] else ' (proposed target)'}")
    return lines


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m app.pic.tools.ai_eval", description=__doc__.split("\n")[0])
    ap.add_argument("--tenant", default="AXN")
    ap.add_argument("--set", action="append", choices=SETS, dest="sets")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    ap.add_argument("--build-sets", action="store_true", help="export the database-derived sets to backend/data/eval")
    ap.add_argument("--database-url", help="database to read (default DATABASE_URL)")
    args = ap.parse_args(argv)
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    import app.pic.services  # noqa: F401
    if args.build_sets:
        print(json.dumps(build_sets(args.tenant), indent=1))
        return 0
    report = evaluate(args.tenant, args.sets)
    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        print("\n".join(summary_lines(report)))
    return 0 if all(g["pass"] for g in report["gates"].values() if g["documented"]) else 1


if __name__ == "__main__":
    sys.exit(main())
