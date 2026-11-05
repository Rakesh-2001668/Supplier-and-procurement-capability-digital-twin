"""M05 bid analysis (SRC-03 Bid Comparison & TCO): the normalised comparison matrix, abnormally low / high bid screens, collusion hints from
data PIC holds, the audited CSV export, the sourcing pipeline and the event history.

Everything here reads the evaluation matrix of ``services.sourcing`` and so is available only after the bids are opened; the entry points go
through ``sourcing.bids_view`` first, which blocks and logs an early attempt.

Screens (rule set SOURCING-POLICY): a screen flags, it never disqualifies; the buyer decides.
    outlier      a total cost below / above the median by more than vsMedianPct, a z-score beyond zScore (from minBids bids), or a price below the
                 should-cost by more than vsShouldCostPct (an abnormally low bid is a delivery and quality risk before it is a saving)
    collusion    identical total costs; identical line pattern (every line of one bid is the same multiple of the other's); shared master data
                 (PAN, bank account, parent company, contact e-mail, address); PIC holds no IP address or director data, so it does not check them
"""
import csv
import hashlib
import io
import statistics
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import AuditEvent, AwardDecision, Bid, SourcingEvent, Supplier, SupplierBankAccount
from app.pic.platform import abac, audit, clock, sourcing_defaults
from app.pic.platform.errors import Problem
from app.pic.services import sourcing
from app.pic.services.common import principal

CENT = Decimal("0.01")


# ---------------------------------------------------------------- outliers
def detect_outliers(tco_by_supplier: dict[str, int], should_cost_minor: Optional[int], policy: dict) -> list[dict]:
    """Pure screen over {supplier: total cost}. Returns [{supplier, flag, detail, ...}] (LOW / HIGH)."""
    cfg = policy.get("outlier") or {}
    flags: list[dict] = []
    values = list(tco_by_supplier.values())
    if not values:
        return flags
    median = Decimal(str(statistics.median(values)))
    vs_median = Decimal(str(cfg.get("vsMedianPct", "30")))
    z_limit = float(cfg.get("zScore", "2.0"))
    min_bids = int(cfg.get("minBids", 3))
    sd = statistics.pstdev(values) if len(values) >= 2 else 0.0
    for supplier, value in tco_by_supplier.items():
        if len(values) >= min_bids and median > 0:
            deviation = (Decimal(value) - median) * 100 / median
            if deviation <= -vs_median:
                flags.append({"supplier": supplier, "flag": "LOW_VS_MEDIAN", "detail": f"{abs(deviation).quantize(CENT)}% below the median total cost", "pct": str(deviation.quantize(CENT))})
            elif deviation >= vs_median:
                flags.append({"supplier": supplier, "flag": "HIGH_VS_MEDIAN", "detail": f"{deviation.quantize(CENT)}% above the median total cost", "pct": str(deviation.quantize(CENT))})
            if sd > 0:
                z = (value - float(statistics.mean(values))) / sd
                if abs(z) >= z_limit:
                    flags.append({"supplier": supplier, "flag": "Z_SCORE", "detail": f"z-score {z:.2f} (limit {z_limit})", "z": round(z, 2)})
        if should_cost_minor:
            vs_should = Decimal(str(cfg.get("vsShouldCostPct", "25")))
            gap = (Decimal(value) - should_cost_minor) * 100 / Decimal(should_cost_minor)
            if gap <= -vs_should:
                flags.append({"supplier": supplier, "flag": "LOW_VS_SHOULD_COST",
                              "detail": f"{abs(gap).quantize(CENT)}% below the should-cost: check scope, quality and the supplier's ability to deliver", "pct": str(gap.quantize(CENT))})
    return flags


# ---------------------------------------------------------------- collusion hints
def _line_pattern(row_a: dict, row_b: dict) -> Optional[Decimal]:
    """The common ratio of two bids over their shared lines when every line price of A is the same multiple of B's (a copied bid), else None."""
    shared = {l["line"]: l["priceMinor"] for l in row_a["lines"]}
    other = {l["line"]: l["priceMinor"] for l in row_b["lines"]}
    keys = sorted(set(shared) & set(other))
    if len(keys) < 2:
        return None
    ratios = [Decimal(shared[k]) / Decimal(other[k]) for k in keys if other[k]]
    if len(ratios) != len(keys):
        return None
    return ratios[0] if max(ratios) - min(ratios) <= Decimal("0.0005") * ratios[0] else None


def collusion_hints(session: Session, event: SourcingEvent, rows: list[dict], policy: dict) -> list[dict]:
    cfg = policy.get("collusion") or {}
    hints: list[dict] = []
    codes = [r["supplier"] for r in rows]
    if cfg.get("identicalTotals", True):
        seen: dict = {}
        for r in rows:
            seen.setdefault(r["tcoMinor"], []).append(r["supplier"])
        for total, suppliers in seen.items():
            if len(suppliers) > 1:
                hints.append({"hint": "IDENTICAL_TOTALS", "suppliers": suppliers, "detail": f"bids with the same total cost {total / 100:,.2f}"})
    if cfg.get("identicalLinePattern", True) and len(rows) > 1:
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                ratio = _line_pattern(a, b)
                if ratio is not None:
                    hints.append({"hint": "LINE_PATTERN", "suppliers": [a["supplier"], b["supplier"]],
                                  "detail": f"every line of {a['supplier']} is {ratio.quantize(Decimal('0.0001'))} times the line of {b['supplier']}"})
    if cfg.get("sharedMasterData", True) and codes:
        suppliers = {s.code: s for s in session.execute(select(Supplier).where(Supplier.code.in_(codes))).scalars()}
        accounts = {}
        for acc in session.execute(select(SupplierBankAccount).where(SupplierBankAccount.supplier_id.in_([s.id for s in suppliers.values()]),
                                                                      SupplierBankAccount.active.is_(True))).scalars():
            accounts.setdefault(acc.supplier_id, []).append((acc.account_masked, acc.ifsc))
        checks = [("PAN", lambda s: s.pan_hash), ("GSTIN", lambda s: s.gstin_hash), ("PARENT", lambda s: s.parent_supplier_id),
                  ("CONTACT_EMAIL", lambda s: (s.contact_email or "").strip().lower() or None),
                  ("ADDRESS", lambda s: ((s.address or {}).get("line1"), (s.address or {}).get("pin")) if (s.address or {}).get("line1") else None)]
        for name, key in checks:
            groups: dict = {}
            for code, supplier in suppliers.items():
                value = key(supplier)
                if value:
                    groups.setdefault(value, []).append(code)
            for group in groups.values():
                if len(group) > 1:
                    hints.append({"hint": f"SHARED_{name}", "suppliers": sorted(group), "detail": f"the bidders share the same {name.replace('_', ' ').lower()} in the supplier master"})
        by_account: dict = {}
        for supplier_id, accs in accounts.items():
            for acc in accs:
                by_account.setdefault(acc, []).append(next(c for c, s in suppliers.items() if s.id == supplier_id))
        for group in by_account.values():
            if len(set(group)) > 1:
                hints.append({"hint": "SHARED_BANK_ACCOUNT", "suppliers": sorted(set(group)), "detail": "the bidders are paid into the same bank account"})
        parents = {s.id: c for c, s in suppliers.items()}
        for code, supplier in suppliers.items():
            if supplier.parent_supplier_id in parents:
                hints.append({"hint": "PARENT_CHILD", "suppliers": sorted([code, parents[supplier.parent_supplier_id]]),
                              "detail": f"{code} is a subsidiary of {parents[supplier.parent_supplier_id]}"})
    return hints


# ---------------------------------------------------------------- the comparison
def comparison(session: Session, event: SourcingEvent) -> dict:
    """SRC-03: the opened bids side by side. Only after the opening (an early call is refused and logged by bids_view)."""
    rows = sourcing.bids_view(session, event)
    pol = sourcing.policy_of(session, event)
    should_cost_minor = (event.should_cost or {}).get("unitCostMinor")
    multi = len(sourcing._lines(session, event)) > 1
    outliers = detect_outliers({r["supplier"]: r["tcoMinor"] for r in rows}, None if multi else should_cost_minor, pol)
    hints = collusion_hints(session, event, rows, pol)
    flagged = {}
    for f in outliers:
        flagged.setdefault(f["supplier"], []).append(f["flag"])
    for r in rows:
        r["flags"] = flagged.get(r["supplier"], [])
    excluded = [{"supplier": session.get(Supplier, b.supplier_id).code, "status": b.status, "round": b.round,
                 "reason": b.disqualified_reason or b.withdrawn_reason or ("no line could be evaluated" if b.status == "INVALID" else None)}
                for b in session.execute(select(Bid).where(Bid.event_id == event.id, Bid.status.in_(("DISQUALIFIED", "WITHDRAWN", "INVALID")))
                                         .order_by(Bid.created_at)).scalars()]
    from app.pic.services import should_cost as should_cost_svc
    benchmark = None
    lines = sourcing._lines(session, event)
    if len(lines) == 1:
        from app.pic.models import Material
        material = session.get(Material, lines[0].material_id) if lines[0].material_id else None
        benchmark = should_cost_svc.benchmark_band(session, material, event.category, event.reference_date, should_cost_minor)
    return {"event": event.number, "status": event.status, "round": event.round, "scoringMethod": event.scoring_method, "currency": event.currency,
            "referenceDate": event.reference_date.isoformat() if event.reference_date else None, "competitive": event.competitive,
            "minBidders": event.min_bidders, "validBidders": len(rows), "baselineMinor": event.baseline_price_minor, "baselineMethod": event.baseline_method,
            "shouldCost": event.should_cost, "benchmark": benchmark, "bids": rows, "excludedBids": excluded, "screens": {"outliers": outliers, "collusion": hints,
            "notChecked": ["IP address of the submission", "directors and shareholders"]}}


# ---------------------------------------------------------------- export
EXPORT_COLUMNS = ["event", "round", "rank", "supplier", "line", "currency", "quoted_price", "price_inr_per_base_unit", "incoterm", "freight", "duty", "packaging",
                  "carrying", "quality", "payment_term_value", "tco_rounding", "tco", "tco_complete", "missing_inputs", "lead_time_days", "payment_terms_days",
                  "moq", "capacity_per_month", "capacity_verified", "price_score", "weighted_score", "valid_until", "submitted_at"]


def export_csv(session: Session, event: SourcingEvent) -> dict:
    """The comparison matrix as CSV (one row per supplier and line) with its SHA-256, audited as COMPARISON_EXPORTED. Only after the bids are opened.
    The file hash and the row count are in the audit trail, so a copy that left the system can be matched to what was exported."""
    abac.guard(session, "SOURCING_EXPORT", event)
    rows = sourcing.bids_view(session, event)  # blocked and logged while sealed
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(EXPORT_COLUMNS)
    count = 0
    for r in rows:
        for l in r["lines"]:
            tco = l["tco"] or {}
            rounding = l["tcoMinor"] - sum(tco.values())
            writer.writerow([event.number, r["round"], r["rank"], r["supplier"], l["line"], l["currency"],
                             f"{Decimal(l['quotedPriceMinor']) / 100:.2f}" if l["quotedPriceMinor"] is not None else "", f"{l['priceMinor'] / 100:.2f}", l["incoterm"] or "",
                             f"{tco.get('freight', 0) / 100:.2f}", f"{tco.get('duty', 0) / 100:.2f}", f"{tco.get('packaging', 0) / 100:.2f}",
                             f"{tco.get('carrying', 0) / 100:.2f}", f"{tco.get('quality', 0) / 100:.2f}", f"{tco.get('paymentTermValue', 0) / 100:.2f}",
                             f"{rounding / 100:.2f}", f"{l['tcoMinor'] / 100:.2f}", "no" if l["tcoIncomplete"] else "yes", ";".join(l["tcoMissing"]),
                             l["leadTimeDays"], l["paymentTermsDays"], l["moq"] or "", l["verifiedCapacityPerMonth"] or "", "yes" if l["capacityVerified"] else "no",
                             r.get("priceScore", ""), r.get("weightedScore", ""), r.get("validUntil") or "", r["submittedAt"]])
            count += 1
    text = out.getvalue()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    audit.record(session, "SOURCING_EVENT", event.id, "COMPARISON_EXPORTED", object_ref=event.number,
                 after={"sha256": digest, "rows": count, "bytes": len(text.encode("utf-8")), "round": event.round, "format": "csv"},
                 reason=f"comparison matrix exported by {principal(session).email}")
    return {"filename": f"{event.number}-comparison-r{event.round}.csv", "sha256": digest, "rows": count, "content": text, "contentType": "text/csv; charset=utf-8"}


# ---------------------------------------------------------------- history and pipeline
def history(session: Session, event: SourcingEvent) -> list[dict]:
    """The event's audit trail, oldest first, with the hash chain position (supplier-facing detail such as bid contents is never in it)."""
    return [{"seq": a.seq, "at": a.ts.isoformat(), "actor": a.actor, "action": a.action, "reason": a.reason, "ruleSet": a.rule_set_version,
             "before": a.before, "after": a.after, "hash": a.hash}
            for a in session.execute(select(AuditEvent).where(AuditEvent.object_type == "SOURCING_EVENT", AuditEvent.object_id == event.id)
                                     .order_by(AuditEvent.seq)).scalars()]


STAGES = [("DRAFT", "Draft"), ("PUBLISHED", "Published"), ("OPEN", "Open"), ("CLOSED", "Closed"), ("UNDER_EVALUATION", "Under evaluation"),
          ("AWARD_PENDING", "Award pending"), ("AWARDED", "Awarded"), ("CANCELLED", "Cancelled")]


def pipeline(session: Session, category: Optional[str] = None) -> dict:
    """The sourcing pipeline (SRC-01 cockpit): events per stage with their value, age in the stage and what each needs next."""
    now = clock.now()
    query = select(SourcingEvent).order_by(SourcingEvent.created_at.desc())
    if category:
        query = query.where(SourcingEvent.category == category)
    stages = {code: {"stage": code, "label": label, "count": 0, "valueMinor": 0, "events": []} for code, label in STAGES}
    next_step = {"DRAFT": "publish", "PUBLISHED": "open", "OPEN": "wait for the close (or extend with a round)", "CLOSED": "open the bids (two people)",
                 "UNDER_EVALUATION": "score, build scenarios, propose the award", "AWARD_PENDING": "approvers decide", "AWARDED": "contract and PO",
                 "CANCELLED": "re-tender if the need stands"}
    for event in session.execute(query).scalars():
        stage = stages.setdefault(event.status, {"stage": event.status, "label": event.status, "count": 0, "valueMinor": 0, "events": []})
        value = int(event.baseline_price_minor or 0)
        age_from = event.closed_at if event.status in ("CLOSED", "UNDER_EVALUATION", "AWARD_PENDING") and event.closed_at else (event.published_at or event.created_at)
        stage["count"] += 1
        stage["valueMinor"] += value
        stage["events"].append({"number": event.number, "title": event.title, "type": event.type, "category": event.category, "round": event.round,
                                "closeAt": event.close_at.isoformat() if event.close_at else None, "ageDays": max(0, (now - age_from).days),
                                "overdue": event.status == "OPEN" and event.close_at is not None and event.close_at < now,
                                "baselineMinor": event.baseline_price_minor, "competitive": event.competitive, "next": next_step.get(event.status)})
    return {"asOf": now.isoformat(), "stages": list(stages.values()), "total": sum(s["count"] for s in stages.values()),
            "open": sum(stages[c]["count"] for c in ("PUBLISHED", "OPEN", "CLOSED", "UNDER_EVALUATION", "AWARD_PENDING") if c in stages)}


def handoff(session: Session, event: SourcingEvent) -> dict:
    """What an award produced and whether orders can be released: the contract draft(s), their state, whether the prices are published to source
    determination, the quota arrangement and the source list entries, and per awarded supplier whether a purchase order may be released today."""
    from app.pic.models import Contract, ContractLine, Material, PriceValidity, QuotaArrangement, QuotaLine, SourceList

    decisions = session.execute(select(AwardDecision).where(AwardDecision.event_id == event.id).order_by(AwardDecision.created_at)).scalars().all()
    out: dict = {"event": event.number, "status": event.status, "decisions": [{"status": d.status, "valueMinor": d.annual_value_minor, "exceptions": d.exceptions,
                                                                                "authority": d.authority, "regretSentAt": d.regret_sent_at.isoformat() if d.regret_sent_at else None}
                                                                               for d in decisions], "contracts": []}
    contracts = session.execute(select(Contract).where(Contract.source_event_id == event.id).order_by(Contract.number)).scalars().all()
    for c in contracts:
        lines = session.execute(select(ContractLine).where(ContractLine.contract_id == c.id)).scalars().all()
        published = session.execute(select(PriceValidity).where(PriceValidity.contract_line_id.in_([l.id for l in lines]), PriceValidity.published.is_(True))).scalars().all() if lines else []
        supplier = session.get(Supplier, c.supplier_id)
        eligible = c.status in ("ACTIVE", "EXPIRING") and bool(published) and supplier.status not in ("BLOCKED", "EXITED")
        reason = None if eligible else (f"contract is {c.status}" if c.status not in ("ACTIVE", "EXPIRING") else
                                        "no price is published to source determination" if not published else f"supplier is {supplier.status}")
        out["contracts"].append({"number": c.number, "supplier": supplier.code, "status": c.status, "validFrom": c.valid_from.isoformat(), "validTo": c.valid_to.isoformat(),
                                 "targetValueMinor": c.target_value_minor, "pricesPublished": len(published), "poReleaseEligible": eligible, "blockedBecause": reason})
    quotas = []
    for q in session.execute(select(QuotaArrangement).where(QuotaArrangement.source_event_id == event.id)).scalars():
        lines = session.execute(select(QuotaLine).where(QuotaLine.quota_id == q.id)).scalars().all()
        quotas.append({"material": session.get(Material, q.material_id).number, "plant": q.plant, "validFrom": q.valid_from.isoformat(), "validTo": q.valid_to.isoformat(),
                       "suppliers": [{"supplier": session.get(Supplier, l.supplier_id).code, "sharePct": str((Decimal(l.share) * 100).quantize(CENT)),
                                      "allocatedQty": str(l.allocated_qty)} for l in lines]})
    out["quotaArrangements"] = quotas
    entries, seen = [], set()
    for c in contracts:
        for line in session.execute(select(ContractLine).where(ContractLine.contract_id == c.id, ContractLine.material_id.is_not(None))).scalars():
            for sl in session.execute(select(SourceList).where(SourceList.supplier_id == c.supplier_id, SourceList.material_id == line.material_id,
                                                               SourceList.plant == line.plant, SourceList.valid_from <= c.valid_to,
                                                               SourceList.valid_to >= c.valid_from)).scalars():
                if sl.id not in seen:
                    seen.add(sl.id)
                    entries.append({"material": session.get(Material, sl.material_id).number, "plant": sl.plant, "supplier": session.get(Supplier, sl.supplier_id).code,
                                    "fixed": sl.fixed, "validFrom": sl.valid_from.isoformat(), "validTo": sl.valid_to.isoformat()})
    out["sourceListEntries"] = entries
    return out


# ---------------------------------------------------------------- what-if
def simulate_tco(session: Session, data: dict) -> dict:
    """The TCO stack of one bid line under the tenant's SOURCING-TCO rule (or the parameters given), with its trace, before any event exists."""
    from app.pic.models import Material
    from app.pic.services import sourcing_tco as tco
    from app.pic.services.common import supplier_by_code

    supplier = supplier_by_code(session, data["supplier"])
    material = session.execute(select(Material).where(Material.number == data["material"])).scalar_one_or_none() if data.get("material") else None
    params = tco.snapshot(session, data.get("tco_params"))
    line = data["line"]
    on = clock.today() if not data.get("on") else __import__("datetime").date.fromisoformat(str(data["on"]))
    try:
        norm = tco.normalise_price(session, line, on, tco.effective(params))
        origin = (line.get("origin") or ("IMPORT" if (supplier.country or "IN") != "IN" else "DOMESTIC")).upper()
        result = tco.compute(session, params=params, supplier_id=supplier.id, category=data["category"], price_minor=norm["minor"], price_exact=norm["exact"],
                             lead_time_days=int(line["lead_time_days"]), payment_terms_days=int(line["payment_terms_days"]),
                             annual_qty=Decimal(str(data["annual_qty"])) if data.get("annual_qty") else None, material=material,
                             freight=Decimal(str(line["freight"])) if line.get("freight") is not None else None,
                             duty=Decimal(str(line["duty"])) if line.get("duty") is not None else None,
                             packaging=Decimal(str(line["packaging"])) if line.get("packaging") is not None else None,
                             incoterm=line.get("incoterm"), origin=origin, hs_code=line.get("hs_code") or (material.hsn_code if material else None))
    except tco.TcoInputError as exc:
        raise Problem(422, "TCO_INPUT", str(exc), rule_ref="SRC-TCO")
    return {"supplier": supplier.code, "rule": params["_rule"], "priceInr": {"minor": norm["minor"], "quotedMinor": norm["quotedMinor"], "currency": norm["currency"],
                                                                         "steps": norm["steps"]},
            "tcoMinor": result["totalMinor"], "parts": result["parts"], "rounding": result["rounding"], "incomplete": result["incomplete"],
            "missing": result["missing"], "trace": result["trace"]}
