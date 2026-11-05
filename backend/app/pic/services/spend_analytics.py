"""Spend analytics on the cube (M01): period comparisons, run-rate, Pareto / ABC and the long tail, supplier counts, savings potential by lever,
the drill from a cube row to its lines and documents, and the CSV export of any slice.

Definitions (also shown in the API responses):

* spend           posted invoices + debit notes - credit notes, net of tax, in the group currency (see services/spend_feed.py);
* addressable     spend that is not intercompany and not in a non-addressable taxonomy segment;
* contract coverage / maverick share   shares of ADDRESSABLE spend;
* YTD             fiscal year to date: the months of the fiscal year (April-March by default, rule SPEND-GOVERNANCE.fiscalYearStartMonth) up to
                  and including the anchor month, against the same months of the previous fiscal year;
* YoY / QoQ       the trailing 12 months against the 12 before; the latest complete fiscal quarter against the one before it;
* run-rate        the average of the last 3 complete months x 12 (annualised);
* share of spend  the row's spend over the spend of all rows of the same filter;
* Pareto / ABC    suppliers (or parents, categories) ranked by spend; class A up to 80% cumulative spend, B up to 95%, C the rest;
                  the long tail are the C suppliers; a net-negative supplier (credits above invoices) is reported apart;
* savings potential   indicative, by lever, from the cube only: CONSOLIDATION (tail spend x aggregationSavingPct), CONTRACT_COVERAGE (addressable
                  spend off contract x contractSavingPct), PRICE_RECOVERY (price paid above contract / standard price). A realised saving is
                  never taken from here: that is the validated ledger of the savings module.
"""
import base64
import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.pic.models import AppUser, SavingsLedgerEntry, SpendCubeSummary, SpendLine, Supplier
from app.pic.platform import audit, clock
from app.pic.platform.errors import Problem
from app.pic.services import spend, spend_cube, spend_scope

C = SpendCubeSummary
CONTRACT_SAVING_PCT_DEFAULT = "4"


def _periods_between(first: str, last: str) -> list[str]:
    out, (y, m) = [], (int(first[:4]), int(first[5:]))
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def anchor_period(session: Session) -> str:
    """The latest complete month with spend (the last month before today, or the latest posted one if that is earlier)."""
    return spend._window(session, 1)[0]


def windows(anchor: str, start_month: int) -> dict:
    """Period sets for the comparisons, all derived from the anchor month."""
    y, m = int(anchor[:4]), int(anchor[5:])
    fy_start_year = y if m >= start_month else y - 1
    ytd = _periods_between(f"{fy_start_year:04d}-{start_month:02d}", anchor)
    prior_ytd = [f"{int(p[:4]) - 1:04d}{p[4:]}" for p in ytd]
    t12 = spend._months_back(date(y, m, 1), 12)
    p12 = spend._months_back(date(y - 1, m, 1), 12)
    # latest complete fiscal quarter ending on or before the anchor, and the one before
    months_into_fy = (m - start_month) % 12 + 1
    complete_quarters = months_into_fy // 3
    q_end_index = y * 12 + (m - 1) - (months_into_fy % 3)
    if complete_quarters == 0:     # first quarter of the fiscal year not complete: take the last two quarters of the previous year
        q_end_index -= 0
    def quarter(end_index: int) -> list[str]:
        return [f"{(end_index - i) // 12:04d}-{(end_index - i) % 12 + 1:02d}" for i in (2, 1, 0)]
    last_q, prev_q = quarter(q_end_index), quarter(q_end_index - 3)
    r3 = spend._months_back(date(y, m, 1), 3)
    return {"ytd": ytd, "priorYtd": prior_ytd, "trailing12": t12, "prior12": p12, "lastQuarter": last_q, "prevQuarter": prev_q, "last3": r3}


def _chg(current: int, base: int) -> Optional[str]:
    return spend_cube._pct(current - base, base) if base > 0 else None


def comparison(session: Session, dims: list, flt: Optional[spend_cube.CubeFilter] = None, anchor: Optional[str] = None, limit: int = 200) -> dict:
    """YTD vs prior-year YTD, YoY (trailing 12 vs the 12 before), QoQ, run-rate and share of spend, by the given dimensions."""
    flt = flt or spend_cube.CubeFilter()
    unknown = [d for d in dims if d not in spend_cube.DIMENSIONS and d not in spend_cube.LEVEL_DIMENSIONS]
    if unknown:
        raise Problem(400, "INVALID_DIMENSION", f"Unknown dimension(s): {', '.join(unknown)}")
    if not 1 <= limit <= spend_cube.MAX_ROWS:
        raise Problem(422, "INVALID_LIMIT", f"limit must be between 1 and {spend_cube.MAX_ROWS}")
    spend_cube.ensure_fresh(session)
    start_month = spend_cube.fiscal_start_month(session)
    anchor = anchor or anchor_period(session)
    if not (len(anchor) == 7 and anchor[4] == "-" and anchor[:4].isdigit() and anchor[5:].isdigit() and 1 <= int(anchor[5:]) <= 12):
        raise Problem(422, "INVALID_PERIOD", "anchor must be YYYY-MM")
    w = windows(anchor, start_month)
    g = C.amount_group_minor
    sums = {name: func.coalesce(func.sum(case((C.period.in_(periods), g), else_=0)), 0) for name, periods in w.items()}
    dims = dims or ["category"]
    sql_dims = list(dict.fromkeys([d for d in dims if d in spend_cube.DIMENSIONS] + (["category"] if any(d in spend_cube.LEVEL_DIMENSIONS for d in dims) else [])))
    where = spend_cube._conditions(session, flt)
    every = sorted(set(sum(w.values(), [])))
    where.append(C.period.in_(every))
    columns = [spend_cube.DIMENSIONS[d].label(d) for d in sql_dims]
    query = select(*columns, *[e.label(k) for k, e in sums.items()]).where(*where)
    if columns:
        query = query.group_by(*[spend_cube.DIMENSIONS[d] for d in sql_dims])
    rows = session.execute(query).mappings().all()
    taxonomy = spend_cube._taxonomy(session) if any(d in spend_cube.LEVEL_DIMENSIONS or d == "category" for d in dims) else {}
    names = spend_cube._supplier_names(session, {r[d] for r in rows for d in ("supplier", "parent_supplier") if d in r})
    buyers = spend_cube._buyer_names(session, {r["buyer"] for r in rows if "buyer" in r})
    merged: dict = {}
    for r in rows:
        key = {}
        for d in dims:
            if d in spend_cube.LEVEL_DIMENSIONS:
                chain = spend_cube._chain(taxonomy, r["category"])
                level = spend_cube.LEVEL_DIMENSIONS[d]
                key[d] = chain[level - 1] if len(chain) >= level else (chain[-1] if chain else r["category"])
            elif d in ("supplier", "parent_supplier"):
                key[d] = names.get(r[d], ("?", ""))[0]
            elif d == "buyer":
                key[d] = buyers.get(r[d], ("", ""))[0] or None
            else:
                key[d] = r[d]
        slot = merged.setdefault(tuple(key.values()), {"key": key, **{k: 0 for k in sums}})
        for k in sums:
            slot[k] += int(r[k] or 0)
    totals = {k: sum(slot[k] for slot in merged.values()) for k in sums}
    out = []
    for slot in sorted(merged.values(), key=lambda s: (-s["trailing12"], [str(v) for v in s["key"].values()])):
        out.append({**slot["key"], "ytdMinor": slot["ytd"], "priorYtdMinor": slot["priorYtd"], "ytdChangePct": _chg(slot["ytd"], slot["priorYtd"]),
                    "trailing12Minor": slot["trailing12"], "prior12Minor": slot["prior12"], "yoyChangePct": _chg(slot["trailing12"], slot["prior12"]),
                    "lastQuarterMinor": slot["lastQuarter"], "prevQuarterMinor": slot["prevQuarter"], "qoqChangePct": _chg(slot["lastQuarter"], slot["prevQuarter"]),
                    "runRateAnnualMinor": slot["last3"] * 4, "sharePct": spend_cube._pct(slot["trailing12"], totals["trailing12"])})
    return {"anchor": anchor, "fiscalYearStartMonth": start_month, "windows": {k: [v[0], v[-1]] for k, v in w.items()}, "dimensions": dims,
            "totals": {"ytdMinor": totals["ytd"], "priorYtdMinor": totals["priorYtd"], "ytdChangePct": _chg(totals["ytd"], totals["priorYtd"]),
                       "trailing12Minor": totals["trailing12"], "prior12Minor": totals["prior12"], "yoyChangePct": _chg(totals["trailing12"], totals["prior12"]),
                       "lastQuarterMinor": totals["lastQuarter"], "prevQuarterMinor": totals["prevQuarter"],
                       "qoqChangePct": _chg(totals["lastQuarter"], totals["prevQuarter"]), "runRateAnnualMinor": totals["last3"] * 4},
            "rows": out[:limit], "truncated": len(out) > limit, "currency": spend_cube._group_currency(session),
            "definitions": {"ytd": "fiscal year to date vs the same months of the previous fiscal year", "yoy": "trailing 12 months vs the 12 before",
                            "qoq": "latest complete fiscal quarter vs the quarter before", "runRate": "average of the last 3 complete months x 12"}}


# ---------------------------------------------------------------- Pareto / ABC / tail
def pareto(session: Session, by: str = "supplier", flt: Optional[spend_cube.CubeFilter] = None, limit: int = 500) -> dict:
    """Suppliers (or parent suppliers, categories) ranked by spend with cumulative share and class A / B / C; the tail and its count."""
    if by not in ("supplier", "parent_supplier", "category"):
        raise Problem(400, "INVALID_DIMENSION", "by must be supplier, parent_supplier or category")
    settings = spend.gov(session)
    a_limit, b_limit = float(settings["paretoA"]), float(settings["paretoB"])
    result = spend_cube.cube(session, [by], flt or spend_cube.CubeFilter(), limit=spend_cube.MAX_ROWS)
    rows = result["rows"]
    positive = [r for r in rows if r["spendMinor"] > 0]
    negative = [r for r in rows if r["spendMinor"] <= 0]
    total = sum(r["spendMinor"] for r in positive)
    cumulative, ranked = 0, []
    for position, r in enumerate(sorted(positive, key=lambda r: (-r["spendMinor"], str(r[by]))), start=1):
        before = cumulative * 100 / total if total else 0
        cumulative += r["spendMinor"]
        share = cumulative * 100 / total if total else 0
        # the item that crosses a boundary belongs to the class it starts in: A is everything that starts below 80% cumulative
        klass = "A" if before < a_limit else "B" if before < b_limit else "C"
        ranked.append({"rank": position, by: r[by], "name": r.get("name") or r.get(f"{by}Name"), "spendMinor": r["spendMinor"],
                       "sharePct": spend_cube._pct(r["spendMinor"], total), "cumulativePct": spend_cube._pct(cumulative, total), "class": klass})
    classes = {k: {"count": 0, "spendMinor": 0} for k in "ABC"}
    for r in ranked:
        classes[r["class"]]["count"] += 1
        classes[r["class"]]["spendMinor"] += r["spendMinor"]
    for k, v in classes.items():
        v["spendPct"] = spend_cube._pct(v["spendMinor"], total)
    tail = classes["C"]
    return {"by": by, "totalMinor": total, "count": len(ranked), "classes": classes, "tailCount": tail["count"], "tailSpendMinor": tail["spendMinor"],
            "tailSpendPct": tail["spendPct"], "tailCountPct": spend_cube._pct(tail["count"], len(ranked)) if ranked else "0",
            "netNegative": [{by: r[by], "spendMinor": r["spendMinor"]} for r in negative if r["spendMinor"] < 0][:20], "rows": ranked[:limit],
            "truncated": len(ranked) > limit, "currency": result["currency"], "thresholds": {"A": a_limit, "B": b_limit}}


def category_structure(session: Session, flt: Optional[spend_cube.CubeFilter] = None) -> dict:
    """Per category: spend, share, number of parent suppliers (and child records), HHI on parents, the top supplier and its share."""
    flt = flt or spend_cube.CubeFilter()
    where = spend_cube._conditions(session, flt)
    rows = session.execute(select(C.category, C.parent_supplier_id, C.supplier_id, func.sum(C.amount_group_minor)).where(*where)
                           .group_by(C.category, C.parent_supplier_id, C.supplier_id)).all()
    by_cat = defaultdict(lambda: defaultdict(int))
    children = defaultdict(set)
    for category, parent, supplier, amount in rows:
        by_cat[category][parent] += int(amount)
        children[category].add(supplier)
    names = spend_cube._supplier_names(session, {p for shares in by_cat.values() for p in shares})
    total = sum(v for shares in by_cat.values() for v in shares.values() if v > 0)
    settings = spend.gov(session)
    out = []
    for category, shares in by_cat.items():
        positive = {k: v for k, v in shares.items() if v > 0}
        cat_total = sum(positive.values())
        if cat_total <= 0:
            continue
        hhi = int(spend.hhi_of(shares))
        top = max(positive.items(), key=lambda kv: (kv[1], str(kv[0])))
        out.append({"category": category, "spendMinor": cat_total, "sharePct": spend_cube._pct(cat_total, total), "suppliers": len(positive),
                    "supplierRecords": len(children[category]), "hhi": hhi,
                    "level": "HIGH" if hhi > settings["hhiHigh"] else "MODERATE" if hhi > settings["hhiModerate"] else "LOW",
                    "topSupplier": names.get(top[0], ("?", ""))[0], "topSupplierName": names.get(top[0], ("?", ""))[1], "topSharePct": spend_cube._pct(top[1], cat_total)})
    return {"totalMinor": total, "rows": sorted(out, key=lambda r: (-r["spendMinor"], r["category"])), "currency": spend_cube._group_currency(session)}


# ---------------------------------------------------------------- savings potential
def savings_potential(session: Session, flt: Optional[spend_cube.CubeFilter] = None) -> dict:
    """Indicative savings by lever over the trailing 12 months (formulas in the module docstring). Not a ledger: nothing here is realised."""
    periods = spend._window(session, 12)
    settings = spend.gov(session)
    consolidation_pct = Decimal(str(settings["aggregationSavingPct"]))
    contract_pct = Decimal(str(settings.get("contractSavingPct", CONTRACT_SAVING_PCT_DEFAULT)))
    flt = flt or spend_cube.CubeFilter()
    where = [*spend_cube._conditions(session, flt), C.period.between(periods[0], periods[-1]), C.addressable.is_(True), C.category != "UNCLASSIFIED"]
    g = C.amount_group_minor
    per_cat = session.execute(select(C.category, func.sum(g), func.coalesce(func.sum(case((C.contracted.is_(False), g), else_=0)), 0),
                                     func.coalesce(func.sum(C.price_variance_group_minor), 0)).where(*where).group_by(C.category)).all()
    per_supplier = defaultdict(list)
    for category, amount in session.execute(select(C.category, func.sum(g)).where(*where).group_by(C.category, C.parent_supplier_id)):
        per_supplier[category].append(int(amount or 0))
    levers = {"CONSOLIDATION": 0, "CONTRACT_COVERAGE": 0, "PRICE_RECOVERY": 0}
    by_category = []
    for category, spend_, off, variance in per_cat:
        spend_, off, variance = int(spend_ or 0), int(off or 0), int(variance or 0)
        if spend_ <= 0:
            continue
        ranked = sorted((x for x in per_supplier[category] if x > 0), reverse=True)
        tail = sum(ranked[3:]) if len(ranked) > 3 else 0
        parts = {"CONSOLIDATION": int(Decimal(tail) * consolidation_pct / 100), "CONTRACT_COVERAGE": int(Decimal(max(off, 0)) * contract_pct / 100),
                 "PRICE_RECOVERY": max(variance, 0)}
        for k, v in parts.items():
            levers[k] += v
        by_category.append({"category": category, "spendMinor": spend_, "totalMinor": sum(parts.values()), **{k.lower() + "Minor": v for k, v in parts.items()}})
    realised = session.execute(select(func.coalesce(func.sum(SavingsLedgerEntry.amount_minor), 0)).where(SavingsLedgerEntry.type == "REALISED")).scalar()
    return {"window": [periods[0], periods[-1]], "currency": spend_cube._group_currency(session), "byLever": levers, "totalMinor": sum(levers.values()),
            "byCategory": sorted(by_category, key=lambda r: (-r["totalMinor"], r["category"]))[:50],
            "assumptions": {"consolidationSavingPct": str(consolidation_pct), "contractSavingPct": str(contract_pct),
                            "priceRecovery": "price paid above contract / standard price, group currency"},
            "realisedLedgerMinor": int(realised or 0), "note": "Indicative potential; realised savings come only from the validated savings ledger."}


# ---------------------------------------------------------------- measure summary
def summary(session: Session, fiscal_year: Optional[str] = None, flt: Optional[spend_cube.CubeFilter] = None) -> dict:
    """The M01 measure set for a fiscal year in one call: spend, invoiced, debit / credit notes, committed, savings, price variance, counts,
    contract coverage, maverick share, addressable share, spend under management, supplier counts, HHI of the largest category, tail."""
    flt = flt or spend_cube.CubeFilter()
    start_month = spend_cube.fiscal_start_month(session)
    if fiscal_year is None:
        fiscal_year = spend_cube.time_label("fiscal_year", anchor_period(session), start_month)
    try:
        months = spend_cube.fiscal_year_periods(fiscal_year, start_month)
    except (ValueError, IndexError):
        raise Problem(422, "INVALID_FISCAL_YEAR", "fiscal_year must look like 2026-27")
    cube = spend_cube.cube(session, ["period"], spend_cube.CubeFilter(**{**flt.__dict__, "period_from": months[0], "period_to": months[-1]}), limit=24,
                           include_commitments=True)
    totals = cube["totals"]
    p = spend.portfolio(session, months[0], months[-1])
    ledger = dict(session.execute(select(SavingsLedgerEntry.type, func.sum(SavingsLedgerEntry.amount_minor)).where(
        SavingsLedgerEntry.posting_date.between(date(int(months[0][:4]), int(months[0][5:]), 1), date(int(months[-1][:4]) + (1 if months[-1][5:] == "12" else 0),
                                                                                                         1 if months[-1][5:] == "12" else int(months[-1][5:]) + 1, 1)))
                                  .group_by(SavingsLedgerEntry.type)).all())
    pareto_ = pareto(session, "parent_supplier", spend_cube.CubeFilter(**{**flt.__dict__, "period_from": months[0], "period_to": months[-1]}), limit=1)
    structure = category_structure(session, spend_cube.CubeFilter(**{**flt.__dict__, "period_from": months[0], "period_to": months[-1]}))
    return {"fiscalYear": fiscal_year, "periods": [months[0], months[-1]], "currency": cube["currency"],
            "spendMinor": totals["spendMinor"], "invoicedMinor": totals["invoicedMinor"], "debitNoteMinor": totals["debitNoteMinor"],
            "creditNoteMinor": totals["creditNoteMinor"], "committedMinor": cube["commitments"]["totals"]["committedMinor"],
            "receivedNotInvoicedMinor": cube["commitments"]["totals"]["receivedNotInvoicedMinor"],
            "savingsRealisedMinor": int(ledger.get("REALISED", 0) or 0), "savingsNegotiatedMinor": int(ledger.get("NEGOTIATED", 0) or 0),
            "priceVarianceMinor": totals["priceVarianceMinor"], "invoices": totals["invoices"], "pos": totals["pos"], "lines": totals["lines"],
            "addressablePct": totals["addressablePct"], "contractCoveragePct": totals["contractCoveragePct"], "maverickPct": totals["maverickPct"],
            "underManagementPct": spend_cube._pct(p["managedMinor"], p["addressableMinor"]),
            "suppliers": pareto_["count"], "tailSuppliers": pareto_["tailCount"], "tailSpendPct": pareto_["tailSpendPct"],
            "maxHhi": max((r["hhi"] for r in structure["rows"]), default=0), "categories": len(structure["rows"]), "fxMissingLines": totals["fxMissingLines"],
            "byPeriod": [{"period": r["period"], "spendMinor": r["spendMinor"], "invoicedMinor": r["invoicedMinor"], "creditNoteMinor": r["creditNoteMinor"]}
                         for r in sorted(cube["rows"], key=lambda r: r["period"])]}


# ---------------------------------------------------------------- drill to lines and documents
def _line_conditions(session: Session, flt: spend_cube.CubeFilter) -> list:
    L = SpendLine
    where = []
    if flt.period_from:
        where.append(L.period >= flt.period_from)
    if flt.period_to:
        where.append(L.period <= flt.period_to)
    if flt.categories:
        where.append(L.category.in_(spend_cube._descendants(spend_cube._taxonomy(session), flt.categories) | set(flt.categories)))
    if flt.suppliers:
        where.append(L.supplier_id.in_(spend_cube._codes_to_ids(session, flt.suppliers) or [spend_cube.NIL]))
    if flt.parents:
        ids = spend_cube._codes_to_ids(session, flt.parents)
        children = list(session.execute(select(Supplier.id).where(Supplier.parent_supplier_id.in_(ids or [spend_cube.NIL]))).scalars())
        where.append(L.supplier_id.in_((ids + children) or [spend_cube.NIL]))
    if flt.plants:
        where.append(L.plant.in_(flt.plants))
    if flt.company_codes:
        where.append(L.company_code.in_(flt.company_codes))
    if flt.cost_centres:
        where.append(and_(L.cost_object_type == "COST_CENTER", L.cost_object.in_(flt.cost_centres)))
    if flt.wbs:
        where.append(and_(L.cost_object_type == "WBS", L.cost_object.in_(flt.wbs)))
    if flt.cost_objects:
        where.append(L.cost_object.in_(flt.cost_objects))
    if flt.currencies:
        where.append(L.currency.in_([c.upper() for c in flt.currencies]))
    if flt.source_systems:
        where.append(L.source_system.in_(flt.source_systems))
    if flt.sources:
        where.append(L.source.in_(flt.sources))
    for column, value in ((L.contracted, flt.contracted), (L.addressable, flt.addressable)):
        if value is not None:
            where.append(column.is_(value))
    if flt.maverick is not None:
        where.append((func.jsonb_array_length(L.maverick_flags) > 0) if flt.maverick else (func.jsonb_array_length(L.maverick_flags) == 0))
    if flt.buyers:
        where.append(L.buyer_id.in_(list(session.execute(select(AppUser.id).where(AppUser.email.in_(flt.buyers))).scalars()) or [spend_cube.NIL]))
    return [*where, *spend_scope.where(session, L)]


def _encode(period: str, line_id) -> str:
    return base64.urlsafe_b64encode(json.dumps([period, str(line_id)]).encode()).decode()


def _decode(cursor: str):
    try:
        period, line_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        import uuid
        return str(period), uuid.UUID(line_id)
    except Exception:  # noqa: BLE001 - any malformed cursor is a client error
        raise Problem(422, "INVALID_CURSOR", "The cursor is not one this API returned")


def lines(session: Session, flt: Optional[spend_cube.CubeFilter] = None, *, cursor: Optional[str] = None, limit: int = 100,
          document_type: Optional[str] = None) -> dict:
    """Drill from a cube slice to its spend lines, newest period first, with keyset pagination (``nextCursor``): stable under inserts, the cost
    of a page does not grow with its depth. Each line names the invoice, the order and, for a note, the note: the document lineage."""
    if isinstance(limit, bool) or not 1 <= limit <= 500:
        raise Problem(422, "INVALID_LIMIT", "limit must be between 1 and 500")
    if document_type is not None and document_type not in ("INVOICE", "CREDIT_NOTE", "DEBIT_NOTE"):
        raise Problem(422, "INVALID_DOCUMENT_TYPE", "document_type must be INVOICE, CREDIT_NOTE or DEBIT_NOTE")
    L = SpendLine
    where = _line_conditions(session, flt or spend_cube.CubeFilter())
    if document_type:
        where.append(L.document_type == document_type)
    if cursor:
        period, line_id = _decode(cursor)
        where.append((L.period < period) | ((L.period == period) & (L.id < line_id)))
    rows = session.execute(select(L).where(*where).order_by(L.period.desc(), L.id.desc()).limit(limit + 1)).scalars().all()
    page = rows[:limit]
    suppliers = {s.id: (s.code, s.legal_name) for s in session.execute(select(Supplier).where(Supplier.id.in_({r.supplier_id for r in page} or {spend_cube.NIL}))).scalars()}
    group_ccy = spend_cube._group_currency(session)
    total, count = session.execute(select(func.coalesce(func.sum(case((L.currency == group_ccy, L.amount_minor), else_=func.coalesce(L.amount_group_minor, 0))), 0),
                                           func.count()).where(*[w for w in where if not cursor or w is not where[-1]])).one()
    out = [{"lineId": str(r.id), "period": r.period, "documentType": r.document_type, "documentRef": r.document_ref or None,
            "documentDate": r.document_date.isoformat() if r.document_date else None, "invoice": r.invoice_ref, "po": r.po_ref,
            "supplier": suppliers.get(r.supplier_id, ("?", "Unknown"))[0], "supplierName": suppliers.get(r.supplier_id, ("?", "Unknown"))[1],
            "category": r.category, "plant": r.plant, "companyCode": r.company_code, "costObject": r.cost_object, "currency": r.currency,
            "amountMinor": r.amount_minor, "amountGroupMinor": r.amount_minor if r.currency == group_ccy else r.amount_group_minor, "fxRate": str(r.fx_rate) if r.fx_rate is not None else None,
            "contracted": r.contracted, "addressable": r.addressable, "maverickFlags": r.maverick_flags, "priceVarianceMinor": r.price_variance_minor or 0,
            "description": r.description, "source": r.source, "sourceSystem": r.source_system,
            "lineage": {"invoice": r.invoice_ref, "purchaseOrder": r.po_ref, "note": r.document_ref or None}} for r in page]
    return {"lines": out, "nextCursor": _encode(page[-1].period, page[-1].id) if len(rows) > limit and page else None,
            "matching": int(count), "matchingGroupMinor": int(total), "currency": group_ccy}


# ---------------------------------------------------------------- export
def export_csv(session: Session, kind: str, dims: list, flt: Optional[spend_cube.CubeFilter] = None) -> dict:
    """CSV of a cube slice (``kind='cube'``, one row per combination of the dimensions) or of its lines (``kind='lines'``), capped at the tenant's
    ``exportMaxRows``; the file's SHA-256 and the filter are written to the audit trail with the user and the row count."""
    flt = flt or spend_cube.CubeFilter()
    cap = int(spend.gov(session)["exportMaxRows"])
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if kind == "cube":
        result = spend_cube.cube(session, dims or ["category"], flt, limit=min(cap, spend_cube.MAX_ROWS))
        fields = ["spendMinor", "invoicedMinor", "debitNoteMinor", "creditNoteMinor", "contractedMinor", "maverickMinor", "addressableMinor", "priceVarianceMinor",
                  "lines", "invoices", "pos", "contractCoveragePct", "maverickPct"]
        writer.writerow([*result["dimensions"], *fields])
        for r in result["rows"]:
            writer.writerow([_cell(r.get(d)) for d in result["dimensions"]] + [r[f] for f in fields])
        rows, truncated, currency = len(result["rows"]), result["truncated"], result["currency"]
    elif kind == "lines":
        header = ["period", "documentType", "documentRef", "invoice", "po", "supplier", "category", "plant", "companyCode", "costObject", "currency",
                  "amountMinor", "amountGroupMinor", "contracted", "addressable", "maverickFlags", "priceVarianceMinor", "description"]
        writer.writerow(header)
        rows, cursor, truncated = 0, None, False
        while rows < cap:
            page = lines(session, flt, cursor=cursor, limit=min(500, cap - rows))
            for r in page["lines"]:
                writer.writerow([_cell(r.get(h) if h != "maverickFlags" else ";".join(r["maverickFlags"])) for h in header])
            rows += len(page["lines"])
            cursor = page["nextCursor"]
            if cursor is None:
                break
        truncated = cursor is not None
        currency = spend_cube._group_currency(session)
    else:
        raise Problem(422, "INVALID_EXPORT", "kind must be cube or lines")
    body = buffer.getvalue().encode("utf-8-sig")
    digest = hashlib.sha256(body).hexdigest()
    principal = session.info.get("principal")
    audit.record(session, "SPEND_EXPORT", principal.user_id if principal else spend_cube.NIL, "EXPORTED", object_ref=f"{kind}:{digest[:12]}",
                 after={"kind": kind, "dimensions": dims, "filters": flt.describe(), "rows": rows, "truncated": truncated, "sha256": digest,
                        "scope": spend_scope.of(session).describe() or None})
    return {"filename": f"spend-{kind}-{clock.today().isoformat()}.csv", "body": body, "sha256": digest, "rows": rows, "truncated": truncated, "currency": currency}


def _cell(value):
    """A CSV cell that a spreadsheet cannot run as a formula (a text that starts with = + - @ is prefixed with an apostrophe)."""
    if value is None:
        return ""
    text_ = str(value)
    return "'" + text_ if text_[:1] in ("=", "+", "@") or (text_[:1] == "-" and not _is_number(text_)) else text_


def _is_number(text_: str) -> bool:
    try:
        float(text_)
        return True
    except ValueError:
        return False
