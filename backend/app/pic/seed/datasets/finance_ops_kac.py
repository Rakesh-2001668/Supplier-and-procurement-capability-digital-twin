"""KAC part of the finance_ops pack: the plan (which purchase order and which migrated invoice plays which case), the event timeline and its execution.

Events are built for the whole timeline first, sorted by business date-time and then executed one transaction each with the clock pinned to that
moment, so a credit note dated 20 October is never netted into a payment dated 2 October. Every event looks its document up by business key
before it writes (supplier invoice number, delivery note, credit note number, payment run date), which makes a second run of the pack a no-op.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select

from app.pic.db import tenant_tx
from app.pic.models import Invoice, InvoiceLine, Material, PoLine, PurchaseOrder, Supplier, SupplierBankAccount
from app.pic.platform import clock
from app.pic.platform.money import line_amount
from app.pic.seed.datasets import finance_ops as F
from app.pic.seed.datasets.finance_ops import Ctx
from app.pic.tools import finance_mock as mock


def weekday_on_or_after(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def clamp(day: date, last: date = F.D(10, 30)) -> date:
    return min(weekday_on_or_after(day), last)


def iso(day: Optional[date]) -> Optional[str]:
    return day.isoformat() if day else None


def day_of(text: Optional[str]) -> Optional[date]:
    return date.fromisoformat(text) if text else None


# ================================================================================================ planning
def eligible_pos(s, company: str) -> list[dict]:
    """Open purchase orders of ACTIVE suppliers with a verified bank account and lines that a plain 3-way match can invoice after a goods receipt:
    goods lines (not service, not inspection-managed, not lot-controlled) with quantity still to receive."""
    banked = set(s.execute(select(SupplierBankAccount.supplier_id).where(SupplierBankAccount.active.is_(True))).scalars())
    # stock materials whose opening position carries a deliberate exception (stock-out, below safety stock or at / below the reorder point) are not
    # received into by this pack: the inventory datasets and their tests rely on those positions
    from app.pic.models import PlanningParameter, Stock
    on_hand: dict = {}
    for mid, plant, stock_type, qty in s.execute(select(Stock.material_id, Stock.plant, Stock.stock_type, func.sum(Stock.qty)).group_by(Stock.material_id, Stock.plant, Stock.stock_type)):
        if stock_type == "UNRESTRICTED":
            on_hand[(mid, plant)] = Decimal(qty)
    risky: set = set()
    planned = set()
    for mid, plant, point in s.execute(select(PlanningParameter.material_id, PlanningParameter.plant, PlanningParameter.reorder_point)):
        planned.add((mid, plant))
        if on_hand.get((mid, plant), Decimal(0)) <= Decimal(point or 0):
            risky.add(mid)
    # the 20 materials the inventory_ops pack opens at plant 1100 (its ledger test explains their balances movement by movement)
    import uuid as _uuid
    from app.pic.models import StockMovement
    ops = _uuid.uuid5(_uuid.NAMESPACE_URL, "KAC-inventory-opening")
    risky |= {mid for (mid,) in s.execute(select(StockMovement.material_id).where(StockMovement.reference_id == ops))}
    out = []
    pos = s.execute(select(PurchaseOrder, Supplier).join(Supplier, Supplier.id == PurchaseOrder.supplier_id).where(
        PurchaseOrder.status.in_(("CONFIRMED", "PARTIALLY_RECEIVED")), PurchaseOrder.company_code == company, PurchaseOrder.currency == "INR",
        Supplier.status == "ACTIVE", Supplier.country == "IN").order_by(PurchaseOrder.number)).all()
    for po, sup in pos:
        if sup.id not in banked or not (po.inherited or {}).get("orderDate"):
            continue
        lines = []
        for pl, material in s.execute(select(PoLine, Material).outerjoin(Material, Material.id == PoLine.material_id).where(
                PoLine.po_id == po.id, PoLine.gr_required.is_(True), PoLine.ir_required.is_(True), PoLine.ses_required.is_(False),
                PoLine.quality_managed.is_(False), PoLine.unit_price_minor > 0, PoLine.purchase_type.in_(("STOCK", "NON_STOCK", "ASSET"))).order_by(PoLine.line_no)).all():
            attrs = (material.attributes or {}) if material is not None else {}
            remaining = pl.qty - pl.received_qty
            if remaining <= 0 or attrs.get("batchManaged") or attrs.get("expiryManaged") or attrs.get("serialManaged") or pl.invoiced_qty > pl.received_qty:
                continue
            if pl.material_id is not None and (pl.material_id in risky or not material.standard_price_minor or (pl.material_id, pl.plant) not in planned):
                continue
            lines.append({"line": pl.line_no, "qty": str(remaining.normalize() if remaining == remaining.to_integral() else remaining), "price": int(pl.unit_price_minor),
                          "gst": str(pl.gst_rate), "hsn": pl.hsn_code or "", "desc": pl.description, "plant": pl.plant, "net": line_amount(remaining, pl.unit_price_minor)})
        if lines:
            out.append({"po": po.number, "supplier": sup.code, "supplier_id": str(sup.id), "name": sup.legal_name, "plant": po.plant, "terms": po.payment_terms, "order_date": po.inherited["orderDate"], "lines": lines, "tds": sup.tds_section, "msme": bool(sup.msme_class),
                        "po_received": po.status != "CONFIRMED"})
    return out


def pick_lines(lines: list[dict], max_lines: int = 2, cap_minor: int = 30 * F.L) -> list[dict]:
    """At most two lines of one plant (one receiver books the receipt), together below INR 30 lakh net."""
    chosen, total = [], 0
    for line in lines:
        if len(chosen) >= max_lines:
            break
        if chosen and line["plant"] != chosen[0]["plant"]:
            continue
        if chosen and total + line["net"] > cap_minor:
            continue
        if not chosen and line["net"] > cap_minor:
            continue
        chosen.append(line)
        total += line["net"]
    return chosen


def build_plan(ctx: Ctx) -> dict:
    """Scenarios from the open purchase orders, migrated payment lists per run and the note / offer picks. Deterministic: purchase orders are
    ordered by their order date and a hash of the PO number."""
    company = ctx.spec["company"]
    with tenant_tx(ctx.tenant_id) as s:
        pos = eligible_pos(s, company)
    pos = [p for p in pos if date.fromisoformat(p["order_date"]) <= F.D(10, 27)]
    pos.sort(key=lambda p: (p["order_date"], mock.unit("po", p["po"])))
    early = [p for p in pos if date.fromisoformat(p["order_date"]) <= F.D(10, 21)]
    used: set = set()

    def take(kind: str, n: int, pool: list[dict], want=None) -> list[dict]:
        got = []
        for p in pool:
            if len(got) == n:
                break
            if p["po"] in used or not pick_lines(p["lines"]) or (want and not want(p)) or (kind in ("MGR_RESOLVED", "MGR_OPEN") and p["po_received"]):
                continue
            if kind == "DUP_VARIANT" and not (len(pick_lines(p["lines"])) >= 2 or Decimal(pick_lines(p["lines"])[0]["qty"]) >= 2):
                continue
            got.append(p)
            used.add(p["po"])
        return got

    scenarios, counter = [], 0
    chosen: dict[str, list[dict]] = {}
    promote_tds, promote_msme = [], []
    breached_ids: set = set()
    for kind, n in KINDS_ORDER():
        pool = early if kind in F.PAID_KINDS else pos
        want = None
        if kind == "PAID_TDS":
            want = lambda p: bool(p["tds"])  # noqa: E731
        elif kind == "PAID_MSME":
            want = lambda p: p["msme"]  # noqa: E731
        elif kind == "PAID_PLAIN":
            want = lambda p: not p["tds"] and not p["msme"]  # noqa: E731
        elif kind == "UNDERPRICED":
            # a price 0.2 % under the order price stays inside the price tolerance (INR 500 per line) only for small lines
            want = lambda p: sum(l["net"] for l in pick_lines(p["lines"])) <= 12_000_000 and all(l["price"] >= 2_000 for l in pick_lines(p["lines"]))  # noqa: E731
        if kind == "PAID_MSME":
            # three deliberate breaches: N15 orders of early invoices, paid in the last run (8-15 days after the due date); the suppliers become MSME
            breach = take(kind, 3, early, lambda p: p["terms"] == "N15" and p["order_date"] <= "2026-10-10")
            breached_ids.update(p["po"] for p in breach)
            promote_msme += [p["supplier"] for p in breach if not p["msme"]]
            chosen["BREACH"] = breach
            n -= len(breach)
        got = take(kind, n, pool, want)
        if kind == "PAID_TDS" and len(got) < n:
            more = take(kind, n - len(got), early, lambda p: not p["msme"])
            promote_tds += [p["supplier"] for p in more]
            got += more
        if kind == "PAID_MSME" and len(got) < n:
            more = take(kind, n - len(got), early, lambda p: not p["tds"])
            promote_msme += [p["supplier"] for p in more]
            got += more
        chosen[kind] = got
    if promote_tds or promote_msme:
        with tenant_tx(ctx.tenant_id) as s:
            for code in dict.fromkeys(promote_tds + promote_msme):
                F.promote(s, s.execute(select(Supplier).where(Supplier.code == code)).scalar_one(), tds=code in promote_tds, msme=code in promote_msme)
    for kind, n in KINDS_ORDER():
        for p in chosen.get(kind, []) + (chosen.get("BREACH", []) if kind == "PAID_MSME" else []):
            counter += 1
            scn = _scenario(counter, kind, p)
            scn["run"] = finish_dates(scn)["run"]
            if p["po"] in breached_ids:
                scn["run"], scn["breach"] = "R6", True
            scenarios.append(scn)
    accepts = [x for x in scenarios if x["kind"] == "PRICE_ACCEPT"]
    if len(accepts) > 1:
        accepts[-1]["leave_pending"] = True           # the buyer has not decided yet: the exception is in resolution
    # DUP_REJECT / DUP_OPEN re-bill an earlier POSTED_OPEN invoice of the plan
    posted_open = [x for x in scenarios if x["kind"] == "POSTED_OPEN"]
    for index, (kind, n) in enumerate([("DUP_REJECT", 2), ("DUP_OPEN", 1)]):
        for k in range(n):
            base = posted_open[(3 * index + k) % len(posted_open)] if posted_open else None
            if base is None:
                break
            counter += 1
            dup = {**{key: base[key] for key in ("po", "supplier", "supplier_id", "name", "plant", "terms", "lines", "order_date")}, "id": f"S{counter:03d}",
                   "kind": kind, "ref": base["id"], "channel": "PDF_OCR", "irn": None}
            dup["inv"] = iso(clamp(day_of(base["inv"]) + timedelta(days=1)))
            dup["inv_no"] = base["inv_no"] + "R"
            dup["gr"] = None
            scenarios.append(dup)
    return {"scenarios": scenarios}


def KINDS_ORDER() -> list:
    return [(k, n) for k, n in F.KINDS if k not in ("DUP_REJECT", "DUP_OPEN")]


def _scenario(n: int, kind: str, p: dict) -> dict:
    sid = f"S{n:03d}"
    order = date.fromisoformat(p["order_date"])
    paid = kind in F.PAID_KINDS
    offset = int(mock.unit(sid, "gr") * 3)
    gr = clamp(max(order + timedelta(days=2), F.D(10, 1)) + timedelta(days=offset), F.D(10, 26) if paid else F.D(10, 27))
    inv = clamp(gr + timedelta(days=1 + int(mock.unit(sid, "inv") * 2)), F.D(10, 28))
    channel = "E_INVOICE" if (kind.startswith("TAX") or mock.unit(sid, "ch") < 0.55) else "PDF_OCR"
    if kind == "MGR_RESOLVED":
        gr = clamp(inv + timedelta(days=2))
    elif kind == "MGR_OPEN":
        gr = None
    return {"id": sid, "kind": kind, "po": p["po"], "supplier": p["supplier"], "supplier_id": p["supplier_id"], "name": p["name"], "plant": p["plant"],
            "terms": p["terms"], "order_date": p["order_date"], "lines": pick_lines(p["lines"]), "gr": iso(gr) if gr else None, "inv": iso(inv),
            "inv_no": f"{F.PREFIX}/{p['supplier']}/{n:04d}", "channel": channel, "irn": None}


def run_for(post_day: date) -> Optional[str]:
    """First payment run at least a day after the posting."""
    for key, day, _ in F.RUNS:
        if day >= post_day + timedelta(days=1):
            return key
    return None


def finish_dates(scn: dict) -> dict:
    """approve / post days and the run the invoice is paid in, from the invoice day and the kind."""
    inv = day_of(scn["inv"])
    kind = scn["kind"]
    after = {"PRICE_CN": 2, "PRICE_ACCEPT": 3, "QTY_CN": 2, "MGR_RESOLVED": 3, "DUP_VARIANT": 2}.get(kind, 1)
    approve = clamp(inv + timedelta(days=after), F.D(10, 29) if kind in F.PAID_KINDS else F.D(10, 30))
    post = approve
    run = run_for(post) if kind in F.PAID_KINDS else None
    return {"approve": iso(approve), "post": iso(post), "run": run}


# ================================================================================================ migrated invoices: payment lists, notes, offers
HOLD_BACK = {"GPF/25-26/0009", "GPF/25-26/0010", "GPF/25-26/0011", "NPC/26-27/0022", "NFW/26-27/0012", "KCC/26-27/0019"}
RUN_QUOTA = {"R1": 14, "R2": 22, "R3": 18, "R4": 28, "R5": 30, "R6": 32}
CN_KINDS = ["PRICE", "QUANTITY", "QUALITY", "RETURN"]
CN_TEXT = {"PRICE": "price difference against the order price found at invoice check",
           "QUANTITY": "short delivery found when the goods were counted in",
           "QUALITY": "parts rejected at incoming inspection and credited",
           "RETURN": "goods returned to the supplier against return delivery"}


def migrated_candidates(s) -> list[dict]:
    banked = set(s.execute(select(SupplierBankAccount.supplier_id).where(SupplierBankAccount.active.is_(True))).scalars())
    linked = dict(s.execute(select(InvoiceLine.invoice_id, func.count()).where(InvoiceLine.po_line_id.is_not(None)).group_by(InvoiceLine.invoice_id)).all())
    lines = dict(s.execute(select(InvoiceLine.invoice_id, func.count()).group_by(InvoiceLine.invoice_id)).all())
    out = []
    for inv, sup in s.execute(select(Invoice, Supplier).join(Supplier, Supplier.id == Invoice.supplier_id).where(
            Invoice.channel == "ERP_MIGRATION", Invoice.status == "POSTED", Invoice.payment_status == "UNPAID", Invoice.payment_block.is_(False)).order_by(Invoice.due_date, Invoice.number)).all():
        out.append({"number": inv.number, "supplier": sup.code, "gross": int(inv.gross_minor), "due": iso(inv.due_date), "posted": iso(inv.posted_at.astimezone(clock.IST).date()),
                    "blocked": sup.status != "ACTIVE", "banked": sup.id in banked, "lines": lines.get(inv.id, 0), "linked": linked.get(inv.id, 0),
                    "invoice_date": iso(inv.invoice_date), "msme": bool(sup.msme_class), "discount_terms": None})
    return out


def plan_migrated(ctx: Ctx, plan: dict) -> None:
    """Which migrated (ERP-loaded) invoices each run pays, which carry credit notes, debit notes, early-payment offers and SCF."""
    with tenant_tx(ctx.tenant_id) as s:
        candidates = migrated_candidates(s)
    by_number = {c["number"]: c for c in candidates}
    hold = set(HOLD_BACK)
    sept = [c for c in candidates if c["invoice_date"] and date.fromisoformat(c["invoice_date"]) >= F.D(9, 1) and c["banked"] and not c["blocked"]]
    hold |= {c["number"] for c in sorted(sept, key=lambda c: mock.unit("hold", c["number"]))[:6]}
    special: set = set(hold)
    runs: dict[str, list[str]] = {key: [] for key, _, _ in F.RUNS + [F.FOREIGN_RUN]}
    plan["msme_late"] = [x["inv_no"] for x in plan["scenarios"] if x.get("breach")]
    # early-payment offers and SCF: well before due, invoices of INR 2 lakh and more
    offer_pool = [c for c in sorted(candidates, key=lambda c: mock.unit("offer", c["number"])) if c["number"] not in special and c["banked"] and not c["blocked"]
                  and 2 * F.L <= c["gross"] <= 25 * F.L]
    offers, scf, taken = [], [], set()
    for run_key, count in (("R4", 4), ("R5", 4), ("R6", 3)):
        run_day = F.RUN_DATE[run_key]
        for c in offer_pool:
            if len([o for o in offers if o["run"] == run_key]) >= count:
                break
            if c["number"] in taken or date.fromisoformat(c["posted"]) > run_day - timedelta(days=7) or date.fromisoformat(c["due"]) < run_day + timedelta(days=10):
                continue
            offers.append({"invoice": c["number"], "supplier": c["supplier"], "run": run_key, "pct": ["1.0", "1.5", "2.0"][len(offers) % 3],
                           "offer_day": iso(clamp(run_day - timedelta(days=3 + len(offers) % 3))), "accept_day": None})
            taken.add(c["number"])
    scf_pool = [c for c in offer_pool if c["number"] not in taken and c["gross"] >= F.L and date.fromisoformat(c["due"]) >= F.D(11, 10)]
    for i, c in enumerate(scf_pool[:4]):
        scf.append({"invoice": c["number"], "supplier": c["supplier"], "day": iso(clamp(F.D(10, 12) + timedelta(days=2 * i))), "run": "R6" if i < 2 else None})
        taken.add(c["number"])
    special |= taken
    for o in offers:
        runs[o["run"]].append(o["invoice"])
    for s_ in scf:
        if s_["run"]:
            runs[s_["run"]].append(s_["invoice"])
    # generic payments: earliest due first, posted at least a day before the run
    pool = [c for c in candidates if c["number"] not in special and c["banked"] and not c["blocked"]]
    for key, day, _ in F.RUNS:
        quota = RUN_QUOTA[key] - len(runs[key])
        for c in list(pool):
            if quota <= 0:
                break
            if date.fromisoformat(c["posted"]) <= day - timedelta(days=1):
                runs[key].append(c["number"])
                pool.remove(c)
                quota -= 1
    # new invoices of the scenarios join the run they are due in
    for scn in plan["scenarios"]:
        if scn.get("run"):
            runs[scn["run"]].append(scn["inv_no"])
    plan["runs"] = runs
    plan["offers"], plan["scf"] = offers, scf
    # credit notes on migrated invoices: ten on invoices paid in later runs (dated before the run), five on invoices still open
    paid_later = [(n, key) for key in ("R3", "R4", "R5", "R6") for n in runs[key] if n in by_number and by_number[n]["lines"] and n not in taken]
    paid_later.sort(key=lambda t: mock.unit("cn", t[0]))
    cns = []
    for i, (number, key) in enumerate(paid_later[:10]):
        day = clamp(F.RUN_DATE[key] - timedelta(days=2 + i % 3))
        day = max(day, clamp(date.fromisoformat(by_number[number]["posted"]) + timedelta(days=1)))
        cns.append({"invoice": number, "supplier": by_number[number]["supplier"], "kind": CN_KINDS[i % 4], "day": iso(day), "n": i + 1})
    open_pool = [c for c in candidates if c["number"] not in special and not c["blocked"] and c["lines"] and c["number"] not in {x["invoice"] for x in cns}
                 and not any(c["number"] in v for v in runs.values())]
    open_pool.sort(key=lambda c: mock.unit("cn-open", c["number"]))
    for i, c in enumerate(open_pool[:5]):
        cns.append({"invoice": c["number"], "supplier": c["supplier"], "kind": CN_KINDS[(i + 1) % 4], "day": iso(clamp(F.D(10, 12) + timedelta(days=3 * i))), "n": 11 + i})
    plan["credit_notes"] = cns
    # debit notes on migrated invoices that carry order lines (price corrections outside the order price go to the buyer chain)
    linked = [c for c in open_pool[5:] if c["linked"]]
    plan["migrated_debit"] = [{"invoice": c["number"], "supplier": c["supplier"], "n": i} for i, c in enumerate(linked[:3])]
    plan["held_back"] = sorted(hold)
