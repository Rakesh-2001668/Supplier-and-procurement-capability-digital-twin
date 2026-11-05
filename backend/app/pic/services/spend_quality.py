"""Data quality of the spend cube (M01): twelve checks on the lines that feed it, a 0-100 score and a stored history.

The cube is only as good as its lines. Every check counts lines and group-currency value, restricted to the reader's scope, and returns a
status (PASS / WARN / FAIL), the penalty it costs and what to do. The score is 100 minus the penalties; a penalty is the check's weight
times its affected share divided by the share at which it fails (capped at the weight). All limits are tenant rule values
(SPEND-GOVERNANCE) with the defaults of ``spend.GOV_DEFAULTS``.

| code | what it finds |
| UNCLASSIFIED         spend in UNCLASSIFIED or waiting in the steward queue (share of value) |
| CATEGORY_NOT_IN_TAXONOMY | lines whose category is not a taxonomy node |
| SUPPLIER_UNKNOWN     lines whose supplier is not in the supplier master |
| FX_RATE_MISSING      foreign-currency lines without a group amount (excluded from every total) |
| FX_RATE_STALE        foreign-currency lines converted with a rate older than ``fxMaxAgeDays`` on the document date |
| DUPLICATE_LINES      the same supplier, invoice, order reference, period, amount and description more than once |
| NON_POSITIVE_INVOICE_LINES | invoice lines of zero or negative value, and credit notes with a positive value (sign error) |
| NO_LINEAGE           platform lines whose invoice line is gone, and lines without any order reference (non-PO spend) |
| INTERCOMPANY_ADDRESSABLE | addressable lines of intercompany suppliers or intercompany categories |
| FUTURE_PERIOD        lines dated after the current month |
| AMOUNT_OUTLIER       single lines above ``outlierAmountMinor`` (default Rs 500 crore): a typing or unit error until proven otherwise |
| FEED_STALE           the newest line is older than ``staleFeedHours``, the cube has not been refreshed, or invoices wait for the spend consumer |
| PERIOD_GAP           a month without any line between the first and the last posted month |
| CUBE_TIE_OUT         the cube summary differs from the lines (stale or damaged summary) |
"""
from datetime import timedelta
from typing import Optional

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.pic.models import ClassificationReview, SpendCubeSummary, SpendLine, SpendQualityRun, Supplier, TaxonomyNode
from app.pic.platform import audit, clock
from app.pic.services import spend, spend_cube, spend_scope

OUTLIER_DEFAULT = 500 * 10_000_000 * 100   # Rs 500 crore in paise

# code -> (name, weight, fail share %, remedy)
CHECKS = {
    "UNCLASSIFIED": ("Unclassified spend", 20, 5, "Work the steward queue; teach the classifier the recurring words"),
    "CATEGORY_NOT_IN_TAXONOMY": ("Category not in the taxonomy", 5, 2, "Add the category to the taxonomy or reclassify the lines"),
    "SUPPLIER_UNKNOWN": ("Supplier not in the master", 8, 1, "Load or correct the supplier master"),
    "FX_RATE_MISSING": ("Foreign lines without an FX rate", 15, 1, "Load the FX rates; the next refresh converts the lines"),
    "FX_RATE_STALE": ("FX rate older than allowed", 5, 5, "Load the missing daily rates"),
    "DUPLICATE_LINES": ("Duplicate spend lines", 10, 0.5, "Find the double load and remove one copy"),
    "NON_POSITIVE_INVOICE_LINES": ("Zero, negative or wrongly signed lines", 8, 1, "Check the source documents; credits belong on credit notes"),
    "NO_LINEAGE": ("Lines without document lineage", 8, 10, "Link the line to its order, or accept it as non-PO spend"),
    "INTERCOMPANY_ADDRESSABLE": ("Intercompany spend counted as addressable", 5, 0.1, "Re-run the addressable rule on the lines"),
    "FUTURE_PERIOD": ("Lines in a future period", 4, 0.1, "Correct the document date"),
    "AMOUNT_OUTLIER": ("Outlier amounts", 4, 0.01, "Verify the unit and the quantity"),
    "FEED_STALE": ("Feed or cube out of date", 12, 100, "Run the cube refresh; check the outbox worker"),
    "PERIOD_GAP": ("Months without any spend", 6, 10, "Check that the extract for the month was loaded"),
    "CUBE_TIE_OUT": ("Cube differs from the lines", 10, 0.01, "Rebuild the cube summary (admin refresh, full)"),
}


def _row(code: str, count: int, value: int, ratio: float, detail: str, samples: Optional[list] = None, extra: Optional[dict] = None) -> dict:
    name, weight, fail, remedy = CHECKS[code]
    status = "PASS" if ratio <= 0 else ("FAIL" if ratio >= fail else "WARN")
    penalty = 0.0 if ratio <= 0 else round(min(float(weight), float(weight) * ratio / fail), 2)
    return {"code": code, "name": name, "status": status, "count": int(count), "valueMinor": int(value), "affectedPct": round(ratio, 3), "failAtPct": fail,
            "weight": weight, "penalty": penalty, "detail": detail, "remedy": remedy, "samples": samples or [], **(extra or {})}


def _group_value(group_ccy: str):
    L = SpendLine
    return func.coalesce(func.sum(case((L.currency == group_ccy, L.amount_minor), else_=func.coalesce(L.amount_group_minor, 0))), 0)


def _samples(session: Session, where: list, limit: int = 5) -> list:
    L = SpendLine
    rows = session.execute(select(L.id, L.invoice_ref, L.period, L.amount_minor, L.currency).where(*where).order_by(func.abs(L.amount_minor).desc(), L.id).limit(limit)).all()
    return [{"lineId": str(r[0]), "invoice": r[1], "period": r[2], "amountMinor": int(r[3]), "currency": r[4]} for r in rows]


def assess(session: Session, persist: bool = False) -> dict:
    """Run every check and return the report (and store it when ``persist``)."""
    L = SpendLine
    scope = spend_scope.where(session, L)
    settings = spend.gov(session)
    group_ccy = spend_cube._group_currency(session)
    gvalue = _group_value(group_ccy)
    total_lines, total_value = session.execute(select(func.count(), func.coalesce(func.sum(func.abs(case((L.currency == group_ccy, L.amount_minor), else_=func.coalesce(L.amount_group_minor, 0)))), 0)).where(*scope)).one()
    total_lines, total_value = int(total_lines), int(total_value)
    checks = []

    def share(value: int) -> float:
        return (abs(value) / total_value * 100) if total_value else 0.0

    def line_share(count: int) -> float:
        return (count / total_lines * 100) if total_lines else 0.0

    def counted(where: list):
        c, v = session.execute(select(func.count(), gvalue).where(*scope, *where)).one()
        return int(c), int(v)

    # 1 unclassified / in queue
    pending = select(ClassificationReview.spend_line_id).where(ClassificationReview.status.in_(("OPEN", "PENDING_SECOND")))
    where = [L.document_type == "INVOICE", (L.category == "UNCLASSIFIED") | L.id.in_(pending)]
    c, v = counted(where)
    checks.append(_row("UNCLASSIFIED", c, v, share(v), f"{c} lines ({spend_cube._pct(abs(v), total_value) if total_value else 0}% of value) are unclassified or waiting for a steward",
                       _samples(session, [*scope, *where])))
    # 2 category not in taxonomy
    nodes = select(TaxonomyNode.code)
    where = [L.document_type == "INVOICE", L.category != "UNCLASSIFIED", L.category.not_in(nodes)]
    c, v = counted(where)
    checks.append(_row("CATEGORY_NOT_IN_TAXONOMY", c, v, share(v), f"{c} lines carry a category that is not a taxonomy node", _samples(session, [*scope, *where])))
    # 3 supplier unknown
    where = [L.supplier_id.not_in(select(Supplier.id))]
    c, v = counted(where)
    checks.append(_row("SUPPLIER_UNKNOWN", c, v, share(v), f"{c} lines have a supplier that is not in the supplier master", _samples(session, [*scope, *where])))
    # 4 fx missing
    where = [L.currency != group_ccy, L.amount_group_minor.is_(None)]
    c = int(session.execute(select(func.count()).where(*scope, *where)).scalar() or 0)
    docs = session.execute(select(L.currency, func.sum(L.amount_minor)).where(*scope, *where).group_by(L.currency)).all()
    checks.append(_row("FX_RATE_MISSING", c, 0, line_share(c), f"{c} foreign-currency lines have no rate; they are left out of every group total" +
                       (": " + ", ".join(f"{k} {int(v or 0)}" for k, v in docs) if docs else ""), _samples(session, [*scope, *where]),
                       {"documentCurrency": {k: int(v or 0) for k, v in docs}}))
    # 5 fx stale: rate older than N days on the document date
    max_age = int(settings["fxMaxAgeDays"])
    on = func.coalesce(L.document_date, func.to_date(L.period + "-01", "YYYY-MM-DD"))
    where = [L.currency != group_ccy, L.fx_date.is_not(None), (on - L.fx_date) > max_age]
    c, v = counted(where)
    checks.append(_row("FX_RATE_STALE", c, v, line_share(c), f"{c} lines were converted with a rate more than {max_age} days older than their document",
                       _samples(session, [*scope, *where])))
    # 6 duplicates
    dup = select(L.supplier_id, L.invoice_ref, L.po_ref, L.period, L.amount_minor, L.description, L.document_type, L.document_ref, func.count().label("n")).where(
        *scope).group_by(L.supplier_id, L.invoice_ref, L.po_ref, L.period, L.amount_minor, L.description, L.document_type, L.document_ref).having(func.count() > 1)
    dups = session.execute(dup.limit(5000)).all()
    extra_lines = sum(int(r[-1]) - 1 for r in dups)
    extra_value = sum((int(r[-1]) - 1) * abs(int(r[4])) for r in dups)
    checks.append(_row("DUPLICATE_LINES", extra_lines, extra_value, share(extra_value), f"{len(dups)} groups of identical lines ({extra_lines} surplus lines)",
                       [{"invoice": r[1], "period": r[3], "amountMinor": int(r[4]), "copies": int(r[-1])} for r in dups[:5]]))
    # 7 non-positive
    # an ERP-history invoice line may be negative (a credit memo of the cutover extract); on the platform an invoice line is positive
    where = [((L.document_type == "INVOICE") & (((L.source != "ERP_HISTORY") & (L.amount_minor <= 0)) | ((L.source == "ERP_HISTORY") & (L.amount_minor == 0))))
             | ((L.document_type == "CREDIT_NOTE") & (L.amount_minor > 0)) | ((L.document_type == "DEBIT_NOTE") & (L.amount_minor <= 0))]
    c, v = counted(where)
    checks.append(_row("NON_POSITIVE_INVOICE_LINES", c, v, line_share(c), f"{c} lines have a value or sign that does not fit their document type",
                       _samples(session, [*scope, *where])))
    # 8 lineage
    from app.pic.models import InvoiceLine
    where = [((L.source == "PLATFORM") & L.invoice_line_id.not_in(select(InvoiceLine.id))) | L.po_ref.is_(None)]
    c, v = counted(where)
    checks.append(_row("NO_LINEAGE", c, v, line_share(c), f"{c} lines cannot be traced to an order or an invoice line", _samples(session, [*scope, *where])))
    # 9 intercompany addressable
    ic = select(Supplier.id).where(Supplier.segment == "INTERCOMPANY")
    where = [L.addressable.is_(True), (L.supplier_id.in_(ic)) | (L.category == "IC-TRANSFER")]
    c, v = counted(where)
    checks.append(_row("INTERCOMPANY_ADDRESSABLE", c, v, share(v), f"{c} intercompany lines are counted as addressable", _samples(session, [*scope, *where])))
    # 10 future period
    current = clock.today().strftime("%Y-%m")
    where = [L.period > current]
    c, v = counted(where)
    checks.append(_row("FUTURE_PERIOD", c, v, line_share(c), f"{c} lines are dated after {current}", _samples(session, [*scope, *where])))
    # 11 outliers
    limit = int(settings.get("outlierAmountMinor", OUTLIER_DEFAULT))
    where = [func.abs(L.amount_minor) > limit]
    c, v = counted(where)
    checks.append(_row("AMOUNT_OUTLIER", c, v, line_share(c), f"{c} single lines exceed {limit}", _samples(session, [*scope, *where])))
    # 12 feed stale
    newest, = session.execute(select(func.max(L.created_at)).where(*scope)).one()
    state = spend_cube.freshness(session)
    age_hours = round((clock.now() - newest).total_seconds() / 3600, 1) if newest else None
    stale_limit = int(settings["staleFeedHours"])
    problems = []
    if age_hours is not None and age_hours > stale_limit:
        problems.append(f"the newest line is {age_hours} h old (limit {stale_limit} h)")
    if state["stale"]:
        problems.append(f"{len(state['dirtyPeriods'])} period(s) wait for a cube refresh" if state["asOf"] else "the cube was never built")
    if state["pendingEvents"]:
        problems.append(f"{state['pendingEvents']} posted document(s) wait for the spend consumer")
    ratio = 100.0 if problems else 0.0
    checks.append(_row("FEED_STALE", state["pendingEvents"], 0, ratio, ("; ".join(problems) or f"cube refreshed {state['asOf']}; newest line {age_hours} h old") if (problems or age_hours is not None) else "no lines",
                       None, {"newestLineAgeHours": age_hours, "cubeAsOf": state["asOf"], "pendingEvents": state["pendingEvents"], "dirtyPeriods": state["dirtyPeriods"]}))
    # 13 period gaps
    periods = [p for (p,) in session.execute(select(L.period).where(*scope).distinct().order_by(L.period))]
    gaps = []
    if periods:
        have = set(periods)
        y, m = int(periods[0][:4]), int(periods[0][5:])
        while f"{y:04d}-{m:02d}" <= min(periods[-1], current):
            if f"{y:04d}-{m:02d}" not in have:
                gaps.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    span = max(1, len(periods) + len(gaps))
    checks.append(_row("PERIOD_GAP", len(gaps), 0, len(gaps) / span * 100, f"no spend in {', '.join(gaps[:6])}" if gaps else "every month has spend", None, {"gaps": gaps}))
    # 14 tie-out: lines vs cube summary (when the cube is current)
    C = SpendCubeSummary
    summary = int(session.execute(select(func.coalesce(func.sum(C.amount_group_minor), 0)).where(*spend_scope.where(session, C))).scalar() or 0)
    lines_value = int(session.execute(select(gvalue).where(*scope)).scalar() or 0)
    diff = lines_value - summary
    tie_ratio = (abs(diff) / abs(lines_value) * 100) if lines_value else 0.0
    if state["stale"] or state["pendingEvents"]:
        tie_ratio = tie_ratio if diff else 0.0
    checks.append(_row("CUBE_TIE_OUT", 1 if diff else 0, abs(diff), tie_ratio, f"lines {lines_value} vs cube {summary} (difference {diff})" if diff else "cube equals the lines",
                       None, {"linesMinor": lines_value, "cubeMinor": summary}))
    score = round(max(0.0, 100.0 - sum(c["penalty"] for c in checks)), 1)
    report = {"score": score, "grade": "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 50 else "D", "lines": total_lines,
              "spendMinor": int(lines_value), "currency": group_ccy, "checks": checks, "runAt": clock.now().isoformat(),
              "failing": [c["code"] for c in checks if c["status"] == "FAIL"], "scope": spend_scope.of(session).describe() or None}
    if persist and not spend_scope.of(session).restricted:
        principal = session.info.get("principal")
        run = SpendQualityRun(tenant_id=principal.tenant_id, score=score, lines=total_lines, spend_group_minor=int(lines_value), checks=checks,
                              run_by=principal.user_id, run_at=clock.now(), created_by=principal.user_id)
        session.add(run)
        session.flush()
        report["runId"] = str(run.id)
        audit.record(session, "SPEND_QUALITY", run.id, "ASSESSED", object_ref=f"score {score}", after={"score": score, "failing": report["failing"]})
    return report


def history(session: Session, limit: int = 30) -> list:
    rows = session.execute(select(SpendQualityRun).order_by(SpendQualityRun.run_at.desc()).limit(limit)).scalars().all()
    return [{"id": str(r.id), "runAt": r.run_at.isoformat(), "score": float(r.score), "lines": r.lines, "spendMinor": r.spend_group_minor,
             "failing": [c["code"] for c in r.checks if c["status"] == "FAIL"]} for r in rows]
