"""Orchestration of the finance_ops pack for KAC: configuration, plan, timeline, execution and summary. Also the debit-note cases and the import masters."""
from __future__ import annotations

import time
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import DebitNote, Invoice, InvoiceLine, Material, PoLine, PoScheduleLine, PurchaseOrder, Supplier, SupplierBankAccount
from app.pic.platform import audit, clock, crypto, workflow
from app.pic.platform.core import next_number
from app.pic.seed.datasets import finance_ops as F
from app.pic.seed.datasets import finance_ops_docs as docs
from app.pic.seed.datasets import finance_ops_kac as plan_mod
from app.pic.seed.datasets import finance_ops_pay as pay
from app.pic.seed.datasets.finance_ops import Ctx, ist
from app.pic.seed.datasets.finance_ops_docs import find_invoice
from app.pic.seed.datasets.finance_ops_kac import clamp, day_of, iso

# Import vendors and orders (MOCK): code, name, country, currency, bank-ish id, plant, lines [(description, group, qty, unit price in currency units, material category or None)]
IMPORTS = [
    ("900001", "Great Lakes Tooling Inc (MOCK import vendor)", "US", "USD", "MOCKUS33XXX", "1100", "N60", [("Progressive die set for bracket BR-4410", "TOOLING", 1, "42500.00", None)]),
    ("900001", "Great Lakes Tooling Inc (MOCK import vendor)", "US", "USD", "MOCKUS33XXX", "1100", "N60", [("Gauge and fixture set for housing HS-220", "TOOLING", 2, "6800.00", None)]),
    ("900002", "Rhein Elektronik GmbH (MOCK import vendor)", "DE", "EUR", "MOCKDEFFXXX", "1200", "N60", [("Hall-effect sensor module", "ELECTRONICS", 2400, "6.35", "ELECTRONICS")]),
    ("900002", "Rhein Elektronik GmbH (MOCK import vendor)", "DE", "EUR", "MOCKDEFFXXX", "1200", "N60", [("Motor driver controller board", "ELECTRONICS", 800, "14.20", "ELECTRONICS")]),
    ("900003", "Nagoya Precision Dies KK (MOCK import vendor)", "JP", "JPY", "MOCKJPJTXXX", "1300", "N90", [("Fine-blanking die insert set", "TOOLING", 3, "1250000", None)]),
]


AXN_ORDERS = [
    ("FOAX01", "Southern Die Maintenance Services (MOCK vendor)", "IN", "INR", "MOCK0000001", "P100", "N30", [("Die maintenance service lot A", "TOOLING", 1, "185000.00", None)]),
    ("FOAX01", "Southern Die Maintenance Services (MOCK vendor)", "IN", "INR", "MOCK0000001", "P100", "N30", [("Die maintenance service lot B", "TOOLING", 2, "96000.00", None)]),
    ("FOAX01", "Southern Die Maintenance Services (MOCK vendor)", "IN", "INR", "MOCK0000001", "P100", "N30", [("Fixture refurbishment lot C", "TOOLING", 1, "142500.00", None)]),
]


def import_masters(ctx: Ctx, imports=None, base: Optional[date] = None, doc_prefix: str = "45009") -> list[dict]:
    """Foreign vendors, their verified bank accounts and open purchase orders, loaded the way the ERP cutover loads open orders (erp_load): they are the
    inputs of the foreign-currency invoices. Seed-if-missing by vendor code and by the order's ERP document number."""
    from app.pic.models import SupplierCategoryStatus
    imports = IMPORTS if imports is None else imports
    base = base or F.D(9, 21)
    out = []
    with ctx.act("admin", ist(base, 9)) as s:
        admin_id = s.info["principal"].user_id
        tid = ctx.tenant_id
        material_by_cat: dict = {}
        for n, (code, name, country, ccy, ifsc, plant, terms, lines) in enumerate(imports, start=1):
            sup = s.execute(select(Supplier).where(Supplier.code == code)).scalar_one_or_none()
            if sup is None:
                account = f"MOCK{code}00{n:04d}"
                sup = Supplier(tenant_id=tid, code=code, legal_name=name, status="ACTIVE", country=country, payment_terms=terms, risk_tier="LOW", segment=None,
                               contact_email=f"ar@{code}.mock.example", created_by=admin_id, screening={"source": "finance_ops", "outcome": "CLEAR", "mock": True},
                               address={"line1": "MOCK import vendor address", "city": country, "country": country})
                s.add(sup)
                s.flush()
                s.add(SupplierBankAccount(tenant_id=tid, supplier_id=sup.id, account_enc=crypto.encrypt(tid, "bank", account), account_masked=crypto.mask(account),
                                          ifsc=ifsc, holder_name=name[:200], active=True, verified_on=base - timedelta(days=20), created_by=admin_id))
                s.add(SupplierCategoryStatus(tenant_id=tid, supplier_id=sup.id, category="TOOLING" if lines[0][1] == "TOOLING" else "ELECTRONICS", status="QUALIFIED",
                                             qualified_on=F.D(9, 1), created_by=admin_id))
                audit.record(s, "SUPPLIER", sup.id, "MIGRATED", object_ref=code, actor=F.ACTOR, reason=F.LABEL,
                             after={"source": "MOCK import vendor master (finance_ops)", "country": country, "currency": ccy})
            erp_doc = f"{doc_prefix}{n:05d}"
            po = s.execute(select(PurchaseOrder).where(PurchaseOrder.erp_doc_no == erp_doc)).scalar_one_or_none()
            if po is None:
                order_day = base + timedelta(days=n)
                total = sum(int((Decimal(q) * Decimal(p) * 100).quantize(Decimal(1))) for _, _, q, p, _ in lines)
                po = PurchaseOrder(tenant_id=tid, number=next_number(s, "PURCHASE_ORDER"), version=1, company_code=ctx.spec["company"], purch_org="1000", plant=plant,
                                   supplier_id=sup.id, status="CONFIRMED", purpose_code="ERP_OPEN_PO", currency=ccy, total_minor=total, payment_terms=terms,
                                   tolerance={"over_pct": "0", "price_pct": "0", "under_pct": "0"},
                                   inherited={"migratedFrom": "MOCK_IMPORT", "erpDocument": erp_doc, "orderDate": order_day.isoformat(), "mock": F.KEY},
                                   rule_set_version="MIGRATION", released_by="MOCK_IMPORT", released_at=ist(order_day, 9), transmitted_via="ERP",
                                   transmitted_at=ist(order_day, 9), erp_doc_no=erp_doc, touchless=False, created_by=admin_id)
                s.add(po)
                s.flush()
                for k, (desc, group, qty, price, category) in enumerate(lines, start=1):
                    material = None
                    if category:
                        material = s.execute(select(Material).where(Material.category == category, Material.status == "ACTIVE", Material.type == "STOCK").order_by(Material.number)
                                             .offset(n)).scalars().first()
                    minor = int((Decimal(price) * 100).quantize(Decimal(1)))
                    line = PoLine(tenant_id=tid, po_id=po.id, line_no=k * 10, item_type="MATERIAL" if material else "FREE_TEXT",
                                  purchase_type="STOCK" if material else "NON_STOCK", material_id=material.id if material else None, description=desc[:200],
                                  material_group=group, qty=Decimal(qty), uom="EA", unit_price_minor=minor, net_minor=int((Decimal(qty) * minor).quantize(Decimal(1))),
                                  gst_rate=Decimal(18), hsn_code="82073000" if group == "TOOLING" else "85423100", need_date=order_day + timedelta(days=14), plant=plant,
                                  storage_location="0001", gr_required=True, ir_required=True, ses_required=False, ers=False, quality_managed=False, price_source="MANUAL",
                                  received_qty=Decimal(0), accepted_qty=Decimal(0), invoiced_qty=Decimal(0), invoiced_minor=0, created_by=admin_id)
                    s.add(line)
                    s.flush()
                    s.add(PoScheduleLine(tenant_id=tid, po_id=po.id, po_line_id=line.id, seq=1, qty=Decimal(qty), delivery_date=order_day + timedelta(days=14),
                                         received_qty=Decimal(0), created_by=admin_id))
                instance = workflow.start(s, "pic.po", "PURCHASE_ORDER", po.id, po.number, {"migratedFrom": "MOCK_IMPORT", "erpDocument": erp_doc})
                workflow.step(s, instance, "F5-06", outcome=f"mock import order {erp_doc} ({ccy})")
                workflow.wait(s, instance, "F5-09", outcome="confirmed: awaiting delivery")
                audit.record(s, "PURCHASE_ORDER", po.id, "MIGRATED", object_ref=po.number, actor=F.ACTOR, reason=F.LABEL,
                             after={"erpDocument": erp_doc, "supplier": code, "currency": ccy, "totalMinor": total})
            plines = list(s.execute(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).scalars())
            out.append({"po": po.number, "supplier": code, "supplier_id": str(sup.id), "currency": ccy, "plant": plant, "order_date": (po.inherited or {})["orderDate"],
                        "lines": [{"line": l.line_no, "qty": str(l.qty.normalize() if l.qty == l.qty.to_integral() else l.qty), "price": int(l.unit_price_minor), "gst": str(l.gst_rate),
                                   "hsn": l.hsn_code or "", "desc": l.description, "plant": l.plant, "net": int(l.net_minor)} for l in plines], "name": sup.legal_name})
    return out


def foreign_scenarios(ctx: Ctx, masters: list[dict], start: int) -> list[dict]:
    out = []
    for i, m in enumerate(masters):
        sid = f"S{start + i:03d}"
        order = date.fromisoformat(m["order_date"])
        gr = clamp(max(order + timedelta(days=6), F.D(10, 6)) + timedelta(days=i))
        inv = clamp(gr + timedelta(days=2))
        out.append({"id": sid, "kind": "FOREIGN", "po": m["po"], "supplier": m["supplier"], "supplier_id": m["supplier_id"], "name": m["name"], "plant": m["plant"],
                    "terms": "N60", "order_date": m["order_date"], "lines": m["lines"], "gr": iso(gr), "inv": iso(inv), "inv_no": f"{F.PREFIX}/{m['supplier']}/{start + i:04d}",
                    "channel": "PDF_OCR", "irn": None, "currency": m["currency"], "run": "RF" if i < 3 else None})
    return out


# ================================================================================================ debit notes
def dn_cases(plan: dict) -> list[dict]:
    """Twelve debit-note cases on new and migrated invoices (see the README for the intended end state of each)."""
    sc = plan["scenarios"]
    by_kind: dict = {}
    for scn in sc:
        by_kind.setdefault(scn["kind"], []).append(scn)
    cases = []
    under, popen = by_kind.get("UNDERPRICED", []), by_kind.get("POSTED_OPEN", [])
    late = next((x for x in by_kind.get("PAID_PLAIN", []) if x.get("run") in ("R3", "R4")), None)
    spec = [("u0", under[0:1], "PRICE_SMALL", "POSTED"), ("u1", under[1:2], "PRICE_SMALL", "MATCHED"), ("u2", under[2:3], "PRICE_SMALL", "APPROVED"),
            ("p0", popen[0:1], "CHARGE", "POSTED"), ("p1", popen[1:2], "CHARGE", "PENDING_APPROVAL"), ("p2", popen[2:3], "CHARGE", "REJECTED"),
            ("p3", popen[3:4], "PRICE_BIG", "PENDING_APPROVAL"), ("p4", popen[4:5], "PRICE_BIG", "REJECTED"), ("lt", [late] if late else [], "PRICE_BIG", "POSTED")]
    for name, target, kind, final in spec:
        if target:
            t = target[0]
            base = clamp(day_of(plan_mod.finish_dates(t)["post"]) + timedelta(days=1 if name != "lt" else 5), F.D(10, 30))
            cases.append({"id": name, "invoice": t["inv_no"], "supplier": t["supplier"], "kind": kind, "final": final, "day": iso(base), "n": len(cases) + 1})
    for i, m in enumerate(plan.get("migrated_debit", [])):
        cases.append({"id": f"m{i}", "invoice": m["invoice"], "supplier": m["supplier"], "kind": ["PRICE_BIG", "PRICE_BIG", "CHARGE"][i % 3],
                      "final": ["PENDING_APPROVAL", "REJECTED", "MATCHED"][i % 3], "day": iso(clamp(F.D(10, 14) + timedelta(days=3 * i))), "n": len(cases) + 1})
    return cases


def ev_dn(ctx: Ctx, case: dict, step: str) -> None:
    from app.pic.services import debit_notes
    note_no = f"DN-{F.PREFIX}-{case['n']:02d}"
    day = day_of(case["day"])
    final = case["final"]
    if step == "submit":
        with ctx.act(F.AP_CAPTURE, ist(day, 10)) as s:
            inv = find_invoice(s, case["supplier"], case["invoice"]) or s.execute(select(Invoice).where(Invoice.number == case["invoice"])).scalar_one_or_none()
            if inv is None or inv.status not in ("POSTED", "PAID") or s.execute(select(DebitNote.id).where(DebitNote.supplier_debit_note_no == note_no,
                                                                                                          DebitNote.supplier_id == inv.supplier_id)).first():
                return
            lines_in = list(s.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.line_no)).scalars())
            if case["kind"] == "CHARGE":
                amount = max(150_000, int((Decimal(inv.net_minor) * Decimal("0.02")).quantize(Decimal(1))))
                lines = [{"kind": "CHARGE", "charge": "FREIGHT", "description": "Freight recovery on late delivery (MOCK sample)", "amount_minor": amount, "gst_rate": "18", "hsn": "996511"}]
            else:
                line = next((l for l in lines_in if l.po_line_id), None)
                if line is None:
                    return
                po_line = s.get(PoLine, line.po_line_id)
                if case["kind"] == "PRICE_SMALL":
                    unit = po_line.unit_price_minor - line.unit_price_minor
                else:
                    unit = max(1, int((Decimal(line.unit_price_minor) * Decimal("0.02")).quantize(Decimal(1), ROUND_HALF_UP)))
                if unit <= 0:
                    return
                lines = [{"kind": "PRICE", "invoice_line": line.line_no, "qty": str(line.qty), "unit_debit_minor": unit}]
            note = debit_notes.submit(s, inv, supplier_debit_note_no=note_no, note_date=day,
                                      reason="MOCK sample: " + ("freight recovery charge" if case["kind"] == "CHARGE" else "price correction against the invoice"), lines=lines)
            ctx.count("debitNotes")
            ctx.count(f"debitNotes:{note.status}")
        return
    with tenant_tx(ctx.tenant_id) as s:
        note = s.execute(select(DebitNote).where(DebitNote.supplier_debit_note_no == note_no)).scalar_one_or_none()
        if note is None:
            return
        note_id, status = note.id, note.status
    if step == "buyers" and status == "PENDING_APPROVAL" and final in ("MATCHED", "APPROVED", "POSTED"):
        ctx.sc.approve_all(note_id, ist(day, 11), "Variance accepted by the buyer (MOCK sample)")
    elif step == "reject" and final == "REJECTED" and status not in ("REJECTED", "POSTED"):
        with ctx.act(F.AP_APPROVE, ist(day, 12)) as s:
            debit_notes.reject(s, s.get(DebitNote, note_id), "MOCK sample: not agreed with the supplier; no recovery on this delivery")
            ctx.count("debitNotesRejected")
    elif step == "approve" and final in ("APPROVED", "POSTED") and status == "MATCHED":
        with ctx.act(F.AP_APPROVE, ist(day, 13)) as s:
            debit_notes.approve(s, s.get(DebitNote, note_id))
    elif step == "post" and final == "POSTED" and status == "APPROVED":
        with ctx.act(F.AP_APPROVE, ist(day, 14)) as s:
            debit_notes.post(s, s.get(DebitNote, note_id))
            ctx.count("debitNotesPosted")


def dn_events(ctx: Ctx, case: dict) -> None:
    day = day_of(case["day"])
    steps = [("submit", 0, 10), ("buyers", 1, 11), ("reject", 1, 12), ("approve", 2, 13), ("post", 2, 14)] if case["final"] != "PENDING_APPROVAL" and case["final"] != "MATCHED" \
        else [("submit", 0, 10), ("buyers", 1, 11)]
    for step, plus, hour in steps:
        d = clamp(day + timedelta(days=plus))
        ctx.at(ist(d, hour, 5), f"DN {case['id']} {step}", lambda step=step: ev_dn(ctx, case, step))
        if step in ("approve", "post"):
            pass


# ================================================================================================ advances
def advance_plan(plan: dict) -> list[dict]:
    """Three advances on orders that also carry a later paid bill of the pack: the first is backed by a bank guarantee."""
    out = []
    for x in sorted((x for x in plan["scenarios"] if x["kind"] in F.PAID_KINDS and x.get("run")), key=lambda x: (x["order_date"], x["id"])):
        day = clamp(max(F.D(10, 5), day_of(x["order_date"]) + timedelta(days=1)), F.D(10, 12))
        post = clamp(day + timedelta(days=2), F.D(10, 14))
        run = next((k for k in ("R3", "R4", "R5") if F.RUN_DATE[k] > post), None)
        if run and day_of(x["inv"]) >= F.RUN_DATE[run] and F.RUN_DATE[x["run"]] > F.RUN_DATE[run] and x["supplier"] not in {a["supplier"] for a in out}:
            out.append({"n": len(out) + 1, "po": x["po"], "supplier": x["supplier"], "scn": x["id"], "guarantee": len(out) == 0, "day": iso(day), "run": run})
        if len(out) == 3:
            break
    return out


def ev_advance(ctx: Ctx, adv: dict, step: str) -> None:
    from app.pic.models import AdvancePayment, BankGuarantee
    from app.pic.services import ind_construction, payables
    day = day_of(adv["day"])
    reference = f"ADV-PI-{F.PREFIX}-{adv['n']:02d}"
    if step == "request":
        with ctx.act(F.AP_CAPTURE, ist(day, 10)) as s:
            if s.execute(select(AdvancePayment.id).where(AdvancePayment.reference == reference)).first():
                return
            po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == adv["po"])).scalar_one()
            total = ind_construction.po_net_total(s, po)
            net = int(Decimal(total) * Decimal("0.15") // 100) * 100
            if adv["guarantee"]:
                gross = net + int(net * Decimal("0.18"))
                ind_construction.record_guarantee(s, po, kind="ADVANCE", bank_name="MOCK Bank (finance_ops)", bank_ref=f"BG-MOCK-{adv['n']:04d}", amount_minor=gross + 100,
                                                  issue_date=F.D(10, 1), expiry_date=F.D(3, 31, 2027))
            ind_construction.request_advance(s, po, net_minor=net, reference=reference, reason="MOCK sample: advance against the supplier's proforma for tooling material")
            ctx.count("advancesRequested")
        if adv["guarantee"]:
            with ctx.act(F.FC_CLOSE, ist(day, 14)) as s:
                guarantee = s.execute(select(BankGuarantee).where(BankGuarantee.bank_ref == f"BG-MOCK-{adv['n']:04d}")).scalar_one()
                if guarantee.status == "PENDING_VERIFICATION":
                    ind_construction.verify_guarantee(s, guarantee, "Confirmed with the issuing bank by letter (MOCK sample)")
        return
    with tenant_tx(ctx.tenant_id) as s:
        advance = s.execute(select(AdvancePayment).where(AdvancePayment.reference == reference)).scalar_one_or_none()
        if advance is None:
            return
        advance_id, status, invoice_id = advance.id, advance.status, advance.invoice_id
    if step == "approve" and status == "REQUESTED":
        ctx.sc.approve_all(advance_id, ist(day + timedelta(days=1), 11), "Advance approved (MOCK sample)")
        ctx.count("advancesApproved")
    elif step == "post" and invoice_id:
        with ctx.act(F.FC_APPROVE, ist(day + timedelta(days=2), 11)) as s:
            inv = s.get(Invoice, invoice_id)
            if inv.status == "MATCHED":
                payables.approve(s, inv)
        with ctx.act(F.AP_POST, ist(day + timedelta(days=2), 12)) as s:
            inv = s.get(Invoice, invoice_id)
            if inv.status == "APPROVED":
                payables.post(s, inv, payables.posting_key(s, inv))
                ctx.count("advancesPosted")


def advance_numbers(ctx: Ctx, run_key: str) -> list[str]:
    from app.pic.models import AdvancePayment
    references = [f"ADV-PI-{F.PREFIX}-{a['n']:02d}" for a in ctx.plan.get("advances", []) if a.get("run") == run_key]
    if not references:
        return []
    with tenant_tx(ctx.tenant_id) as s:
        return [n for (n,) in s.execute(select(Invoice.number).join(AdvancePayment, AdvancePayment.invoice_id == Invoice.id).where(
            AdvancePayment.reference.in_(references), Invoice.status == "POSTED", Invoice.payment_status == "UNPAID"))]


# ================================================================================================ rebates
REBATES = [("KAC-MA-0004", "MOCK volume rebate FY2026-27 (value tiers, quarterly)", "QUARTERLY", [{"from": "0", "ratePct": "0.5"}, {"from": "10000000", "ratePct": "1.0"}]),
           ("KAC-MA-0005", "MOCK volume rebate FY2026-27 (value tiers, monthly)", "MONTHLY", [{"from": "0", "ratePct": "0.3"}, {"from": "5000000", "ratePct": "0.6"}])]


def rebate_agreements(ctx: Ctx) -> None:
    """Two supplier-scope rebate agreements on KAC's master agreements, accrued for September (the period a settlement can follow)."""
    from app.pic.models import Contract, RebateAgreement
    from app.pic.services import rebates
    for number, title, period, tiers in REBATES:
        with ctx.act("contract.manager", ist(F.D(10, 6), 10)) as s:
            if s.execute(select(RebateAgreement.id).where(RebateAgreement.title == title)).first():
                continue
            contract = s.execute(select(Contract).where(Contract.number == number)).scalar_one_or_none()
            if contract is None:
                ctx.skipped.append(f"rebate agreement on {number}: the contract does not exist")
                continue
            agreement = rebates.create_agreement(s, contract, title=title, basis="VALUE", period=period, tiers=tiers, tier_mode="RETROACTIVE", scope="SUPPLIER",
                                                 valid_from=F.D(4, 1), valid_to=F.D(3, 31, 2027))
            rebates.accrue(s, agreement, F.D(9, 30))
            ctx.count("rebateAgreements")


def rebate_settle(ctx: Ctx) -> None:
    from app.pic.models import RebateAccrual, RebateAgreement, RebateSettlement
    from app.pic.services import rebates
    with ctx.act("fin.controller.2", ist(F.D(10, 8), 10)) as s:
        agreement = s.execute(select(RebateAgreement).where(RebateAgreement.title == REBATES[0][1])).scalar_one_or_none()
        if agreement is None:
            return
        accrual = s.execute(select(RebateAccrual).where(RebateAccrual.agreement_id == agreement.id, RebateAccrual.status == "OPEN", RebateAccrual.accrued_minor > 0,
                                                         RebateAccrual.period_end <= F.D(9, 30)).order_by(RebateAccrual.period_start)).scalars().first()
        if accrual is not None and not s.execute(select(RebateSettlement.id).where(RebateSettlement.accrual_id == accrual.id)).first():
            rebates.settle(s, accrual)
            ctx.count("rebateSettlements")


def rebate_accrue(ctx: Ctx) -> None:
    from app.pic.services import rebates
    with ctx.act("contract.manager", ist(F.D(10, 30), 9)) as s:
        result = rebates.accrue_all(s, F.D(10, 30))
        ctx.count("rebateAccruals", result["agreements"])


# ================================================================================================ the run
def configure(ctx: Ctx) -> dict:
    """Stage 1: rules, users, supplier tax attributes, FX series and the foreign masters (everything the documents need)."""
    done = F.stage_done(ctx.tenant_id, "config")
    if done is not None:
        return done
    with tenant_tx(ctx.tenant_id) as s:                  # the receiving area of every plant (inventory_ops creates it for plant 1100 only)
        from app.pic.models import StorageLocation
        have = {(x.plant, x.code) for x in s.execute(select(StorageLocation)).scalars()}
        for plant in ctx.spec["plants"]:
            if (plant, docs.RECEIVING_SLOC) not in have:
                s.add(StorageLocation(tenant_id=ctx.tenant_id, plant=plant, code=docs.RECEIVING_SLOC, name="Goods receiving (MOCK, finance_ops)"))
    out = {"rules": F.kac_rules(ctx.tenant_id)}
    out["users"] = F.ensure_users(ctx)
    out["attributes"] = F.assign_finance_attributes(ctx)
    out.update(F.load_fx(ctx))
    F.stage_mark(ctx.tenant_id, "config", out)
    return out


def plan_all(ctx: Ctx) -> dict:
    done = F.stage_done(ctx.tenant_id, "plan")
    if done is not None:
        return done
    plan = plan_mod.build_plan(ctx)
    masters = import_masters(ctx)
    plan["scenarios"] += foreign_scenarios(ctx, masters, len(plan["scenarios"]) + 1)
    plan_mod.plan_migrated(ctx, plan)
    plan["advances"] = advance_plan(plan)
    plan["debit_cases"] = dn_cases(plan)
    late = next((c for c in plan["debit_cases"] if c["id"] == "lt"), None)
    if late:
        plan["runs"]["R6"].append(late["invoice"])
    plan["runs"]["RF"] = [x["inv_no"] for x in plan["scenarios"] if x["kind"] == "FOREIGN" and x.get("run") == "RF"]
    suppliers = sorted({o["supplier"] for o in plan["offers"]} | {s["supplier"] for s in plan["scf"]})
    plan["portal_suppliers"] = suppliers
    F.stage_mark(ctx.tenant_id, "plan", plan)
    return plan


def certificates_for(ctx: Ctx, plan: dict) -> int:
    tds_runs = [x for x in plan["scenarios"] if x["kind"] == "PAID_TDS"]
    seen, picks = set(), []
    for x in tds_runs:
        if x["supplier"] in seen:
            continue
        seen.add(x["supplier"])
        i = len(picks)
        if i >= 4:
            break
        valid_to = [F.D(3, 31, 2027), F.D(11, 15), F.D(3, 31, 2027), F.D(5, 31, 2027)][i]
        note = ["lower deduction 1 % on the section", "certificate expires on 15 Nov 2026: renewal due", "lower deduction 0.5 %; the certificate states an amount cap of INR 25,00,000 "
                "(enforced when the service carries the cap field)", "lower deduction 1 % on the section"][i]
        picks.append((x["supplier"], f"LDC-MOCK-2627-{i + 1:04d}", Decimal(["1.0", "1.0", "0.5", "1.0"][i]), F.D(4, 1), valid_to, note,
                      2_500_000_00 if i == 2 else None))
    return F.certificates(ctx, picks)


def build_events(ctx: Ctx, plan: dict) -> None:
    for scn in plan["scenarios"]:
        docs.build_scenario_events(ctx, scn)
    for case in plan["debit_cases"]:
        dn_events(ctx, case)
    for cn in plan["credit_notes"]:
        ctx.at(ist(day_of(cn["day"]), 14, 30), f"CN M{cn['n']}", lambda cn=cn: pay.ev_migrated_credit_note(ctx, cn))
    for o in plan["offers"]:
        d = day_of(o["offer_day"])
        ctx.at(ist(d, 10), f"offer {o['invoice']}", lambda o=o: pay.ev_offer(ctx, o))
    for o in plan["scf"]:
        ctx.at(ist(day_of(o["day"]), 11), f"scf {o['invoice']}", lambda o=o: pay.ev_scf(ctx, o))
    for adv in plan.get("advances", []):
        for step, plus, hour in (("request", 0, 10), ("approve", 1, 11), ("post", 2, 11)):
            ctx.at(ist(day_of(adv["day"]) + timedelta(days=plus), hour), f"advance {adv['n']} {step}", lambda adv=adv, step=step: ev_advance(ctx, adv, step))
    for key in ("R3", "R4", "R5"):          # the payment.completed event of an advance document marks the advance PAID: relay right after the run
        ctx.at(ist(F.RUN_DATE[key], 10, 30), f"relay after run {key}", lambda key=key: kit_relay(ctx, F.RUN_DATE[key], 10, 40))
    ctx.at(ist(F.D(10, 6), 10), "rebate agreements", lambda: rebate_agreements(ctx))
    ctx.at(ist(F.D(10, 8), 10), "rebate settlement", lambda: rebate_settle(ctx))
    ctx.at(ist(F.D(10, 30), 9), "rebate accrual", lambda: rebate_accrue(ctx))
    # periods
    close_day, months = F.PERIODS_CLOSE_1
    for month in months:
        ctx.at(ist(close_day, 10), f"close {month}", lambda month=month: pay.ev_close(ctx, month, close_day, f"{F.LABEL}: month-end close"))
    ctx.at(ist(F.PERIOD_SEP_CLOSE, 10), "close 2026-09", lambda: pay.ev_close(ctx, "2026-09", F.PERIOD_SEP_CLOSE, f"{F.LABEL}: month-end close"))
    ctx.at(ist(F.PERIOD_SEP_REOPEN, 10), "reopen 2026-09", lambda: pay.ev_reopen(ctx, "2026-09", F.PERIOD_SEP_REOPEN,
                                                                                f"{F.LABEL}: late TDS challan adjustment for September booked by the tax team"))
    ctx.at(ist(F.PERIOD_SEP_RECLOSE, 10), "reclose 2026-09", lambda: pay.ev_reclose(ctx, "2026-09", F.PERIOD_SEP_RECLOSE, f"{F.LABEL}: closed again after the adjustment"))
    # runs, files, acknowledgements, statements
    for key, day, _ in F.RUNS + [F.FOREIGN_RUN]:
        ctx.at(ist(day, 10), f"run {key}", lambda key=key: pay.ev_run(ctx, key))
        ctx.at(ist(day, 11), f"file {key}", lambda key=key: pay.ev_file(ctx, key))
    for key, ack_day in (("R1", F.D(9, 19)), ("R2", F.D(10, 3)), ("R4", F.D(10, 19)), ("R6", F.D(11, 2) if False else F.D(10, 31))):
        ctx.at(ist(ack_day, 9), f"ack {key}", lambda key=key, ack_day=ack_day: pay.ev_ack(ctx, key, ack_day))
    ctx.at(ist(F.D(10, 12), 12), "results R3", lambda: pay.ev_manual_results(ctx, "R3", F.D(10, 12)))
    ctx.at(ist(F.D(10, 31), 12), "results RF", lambda: pay.ev_manual_results(ctx, "RF", F.D(10, 31)))
    for key, fmt, run_key, day, account in pay.STATEMENTS:
        ctx.at(ist(day, 18), f"statement {key}", lambda a=(key, fmt, run_key, day, account): pay.ev_statement(ctx, *a))


def kit_relay(ctx: Ctx, day: date, hour: int = 12, minute: int = 30) -> None:
    from app.pic.seed.datasets import _tenant_kit as kit
    kit.relay(ctx.sc, ist(day, hour, minute))


def execute(ctx: Ctx) -> None:
    events = sorted(ctx.events, key=lambda e: (e.when, e.seq))
    for index, ev in enumerate(events, start=1):
        started = time.time()
        try:
            ev.fn()
        except F.Skip as skip:
            ctx.skipped.append(f"{ev.label}: {skip}")
        except Exception as exc:
            exc.add_note(f"finance_ops event {index}/{len(events)}: {ev.label} at {ev.when.isoformat()}")
            raise
        if time.time() - started > 30:
            F.log.warning("finance_ops slow event %s: %.1f s", ev.label, time.time() - started)


def run(ctx: Ctx) -> dict:
    started = time.time()
    config = configure(ctx)
    plan = plan_all(ctx)
    ctx.plan = plan
    clock.set_pinned(ist(F.D(9, 1), 9))
    F.supplier_portal_users(ctx, plan["portal_suppliers"])
    certs = certificates_for(ctx, plan)
    build_events(ctx, plan)
    execute(ctx)
    from app.pic.seed.datasets import _tenant_kit as kit
    kit.relay(ctx.sc, ist(F.D(10, 31), 22))
    ctx.counts.update({"certificates": certs})
    notes = [f"Config ({F.LABEL}): rules {', '.join(config['rules']['published']) or 'already published'}; {config['users']} user(s); supplier tax attributes {config['attributes']}; "
             f"{config['fxRates']} FX rate row(s)",
             f"Documents and payments: {ctx.counts}", f"Skipped steps: {ctx.skipped}" if ctx.skipped else "No step was skipped",
             f"Duration {time.time() - started:.0f} s"]
    return {"notes": notes, "counts": dict(ctx.counts), "label": F.LABEL, "statements": [pay.statement_file_name(sp) for sp in ctx.plan.get("statements", [])],
            "skipped": ctx.skipped}
