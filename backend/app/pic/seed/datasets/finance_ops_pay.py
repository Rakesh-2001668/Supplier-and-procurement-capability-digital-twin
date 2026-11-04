"""Payments, bank files and statements, notes, early payment and period events of the finance_ops pack for KAC."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import CreditNote, Invoice, InvoiceLine, Payment, PaymentFile, PostingPeriod, Supplier
from app.pic.platform import audit
from app.pic.seed.datasets import finance_ops as F
from app.pic.seed.datasets.finance_ops import Ctx, ist
from app.pic.seed.datasets.finance_ops_kac import CN_TEXT, clamp, day_of
from app.pic.tools import finance_mock as mock

FILE_FORMAT = {"R1": "ISO20022_PAIN001", "R2": "ISO20022_PAIN001", "R3": "NEFT_CSV", "R4": "ISO20022_PAIN001", "R5": "ISO20022_PAIN001",
               "R6": "ISO20022_PAIN001", "RF": "ISO20022_PAIN001"}
# statements: (key, format, run, day it is issued, bank account key)
STATEMENTS = [("S1", "camt053", "R1", F.D(9, 21), "A"), ("S2", "camt053", "R2", F.D(10, 5), "A"), ("S3", "camt053", "R4", F.D(10, 19), "A"),
              ("S4", "mt940", "R5", F.D(10, 26), "B"), ("S5", "mt940", "R6", F.D(10, 31), "B")]
BANK = {"A": ("HDFC", "MOCK-CA-0001"), "B": ("ICIC", "MOCK-CA-0002")}
OPENING_MINOR = 4_000_000_000   # INR 4 crore opening balance, a MOCK number


# ================================================================================================ payment runs
def ev_run(ctx: Ctx, key: str) -> None:
    from app.pic.services import payables
    marker = f"run:{key}"
    if F.stage_done(ctx.tenant_id, marker) is not None:
        return
    day = F.RUN_DATE[key]
    numbers = ctx.plan["runs"].get(key, [])
    with ctx.act(F.TREASURY, ist(day, 10)) as s:
        existing = [n for n in numbers if s.execute(select(Invoice.id).where(Invoice.number == n)).first()]
        from app.pic.seed.datasets import finance_ops_run
        existing += [n for n in finance_ops_run.advance_numbers(ctx, key) if n not in existing]      # the approved, posted advances planned for this run
        if not existing:
            # payment_run treats an empty invoice list as "every due invoice": never call it without a selection
            F.stage_mark(ctx.tenant_id, marker, {"run": None, "paid": [], "skipped": []})
            return
        result = payables.payment_run(s, day, include_not_due=True, invoice_numbers=existing)
        for item in result["paid"]:
            if item.get("msmeInterestMinor"):
                inv = s.execute(select(Invoice).where(Invoice.number == item["invoice"])).scalar_one()
                audit.record(s, "INVOICE", inv.id, "MSME_INTEREST_ASSESSED", object_ref=inv.number,
                             reason="MSMED Act s.16: interest on a payment made after the due date (MOCK bank rate; the figure is not posted anywhere)",
                             after={"payment": item["payment"], "dueDate": item["dueDate"], "paidOn": day.isoformat(), "interestMinor": item["msmeInterestMinor"],
                                    "bankRatePct": F.MSME_BANK_RATE, "multiple": 3})
                ctx.count("msmeBreachesWithInterest")
    ctx.count("paymentRuns")
    ctx.count("payments", len(result["paid"]))
    F.stage_mark(ctx.tenant_id, marker, {"run": result["run"], "paid": [{k: v for k, v in p.items() if k in ("invoice", "payment", "amountMinor", "tdsMinor", "discountMinor",
                                                                                                         "msme", "msmeInterestMinor", "currency", "dueDate")} for p in result["paid"]],
                                         "skipped": result["skipped"]})


def _run_ref(ctx: Ctx, key: str) -> str:
    done = F.stage_done(ctx.tenant_id, f"run:{key}")
    if done is None:
        raise F.Skip(f"run {key} has not been executed")
    return done["run"]


def ev_file(ctx: Ctx, key: str) -> None:
    """Payment file of the run, marked SENT. R5's pain.001 is rejected by the bank and replaced by a NEFT file; R3 goes out as a NEFT file."""
    from app.pic.services import bank_files
    marker = f"file:{key}"
    if F.stage_done(ctx.tenant_id, marker) is not None:
        return
    run_ref = _run_ref(ctx, key)
    day = F.RUN_DATE[key]
    names = []
    with ctx.act(F.TREASURY, ist(day, 11)) as s:
        if not s.execute(select(Payment.id).where(Payment.run_ref == run_ref, Payment.status == "COMPLETED")).first():
            F.stage_mark(ctx.tenant_id, marker, {"file": None})
            return
        pf = bank_files.generate(s, run_ref, FILE_FORMAT[key])
        bank_files.content_of(s, pf)                                       # downloaded for the bank portal (audited)
        bank_files.set_status(s, pf, "SENT")
        names.append(pf.number)
        if key == "R5":
            bank_files.set_status(s, bank_files.by_number(s, pf.number, lock=True), "REJECTED",
                                  reason="MOCK bank: the pain.001 host-to-host mandate of the new account B is not active yet; resubmit as a NEFT bulk file")
            replacement = bank_files.generate(s, run_ref, "NEFT_CSV")
            bank_files.content_of(s, replacement)
            bank_files.set_status(s, replacement, "SENT")
            names.append(replacement.number)
    ctx.count("paymentFiles", len(names))
    F.stage_mark(ctx.tenant_id, marker, {"files": names})


def ev_ack(ctx: Ctx, key: str, day: date) -> None:
    from app.pic.services import bank_files
    marker = f"ack:{key}"
    if F.stage_done(ctx.tenant_id, marker) is not None:
        return
    files = (F.stage_done(ctx.tenant_id, f"file:{key}") or {}).get("files") or []
    if not files:
        return
    with ctx.act(F.TREASURY, ist(day, 10)) as s:
        pf = bank_files.by_number(s, files[-1], lock=True)
        if pf.status == "SENT":
            bank_files.set_status(s, pf, "ACKNOWLEDGED", bank_ref=f"MOCK-ACK-{key}-{day.strftime('%y%m%d')}")
            ctx.count("filesAcknowledged")
    F.stage_mark(ctx.tenant_id, marker, {"file": files[-1]})


def run_payments(s, run_ref: str) -> list[dict]:
    rows = s.execute(select(Payment, Supplier.code).join(Supplier, Supplier.id == Payment.supplier_id).where(Payment.run_ref == run_ref)
                     .order_by(Payment.number)).all()
    return [{"number": p.number, "amountMinor": int(p.amount_minor), "valueDate": p.value_date.isoformat(), "supplier": code, "status": p.status,
             "bankStatus": p.bank_status, "currency": p.currency} for p, code in rows]


# ================================================================================================ bank statements
def statement_spec(ctx: Ctx, key: str, fmt: str, run_key: str, day: date, account: str) -> dict:
    """The deliberate content of the statement, decided from the run's payments (in payment-number order)."""
    run_ref = _run_ref(ctx, run_key)
    with tenant_tx(ctx.tenant_id) as s:
        pays = [p for p in run_payments(s, run_ref) if p["status"] == "COMPLETED" and p["currency"] == "INR"]
    numbers = [p["number"] for p in pays]
    spec = {"key": key, "format": fmt, "run": run_ref, "runKey": run_key, "day": day.isoformat(), "account": BANK[account][1], "bank": BANK[account][0],
            "payments": numbers, "returned": [], "ambiguous": [], "unmatched": [], "opening": OPENING_MINOR - 7_000_000_000 * (0 if key == "S1" else int(key[1]) - 1) // 10}
    if key == "S2" and len(numbers) >= 4:
        spec["ambiguous"] = numbers[-2:]
        spec["unmatched"] = [{"text": f"Customer receipt INV 5521 {mock.TAG}", "amountMinor": 1_250_000_00, "ref": mock.utr("HDFC", day, 99)}]
    if key == "S3" and numbers:
        spec["returned"] = [numbers[len(numbers) // 2]]
    if key == "S4" and len(numbers) >= 3:
        spec["returned"] = [numbers[1], numbers[-1]]
    spec["reasons"] = {"S3": "AC04 Beneficiary account closed", "S4": "AC01 Incorrect account number / IFSC"}.get(key, "")
    return spec


def statement_text(spec: dict, pays: dict[str, dict]) -> str:
    """The statement file of a spec from its payments ({number: payment row})."""
    day = date.fromisoformat(spec["day"])
    bank = spec["bank"]
    entries = []
    batch = [pays[n] for n in spec["ambiguous"]]
    for n, number in enumerate(spec["payments"], start=1):
        p = pays[number]
        ref = mock.utr(bank, day, n)
        if number in spec["ambiguous"]:
            continue
        if number in spec["returned"]:
            entries.append({"amountMinor": p["amountMinor"], "direction": "CRDT", "returned": True, "payment": number, "bankRef": ref.replace("MOCK", "MRTN", 1),
                            "reason": spec["reasons"] or "Returned by the bank", "rsn": spec["reasons"][:4] or "AC04", "text": f"Return of {number} {mock.TAG}",
                            "date": spec["day"]})
        else:
            entries.append({"amountMinor": p["amountMinor"], "direction": "DBIT", "payment": number, "text": f"{number} {p['supplier']} {mock.TAG}", "bankRef": ref,
                            "date": p["valueDate"]})
    if batch:
        # the bank nets its charge (INR 175) off the bulk booking, so the amount is not the sum of the two payments: the importer cannot split it and reports AMBIGUOUS
        entries.append({"amountMinor": sum(p["amountMinor"] for p in batch) - 17_500, "direction": "DBIT", "payment": None, "bankRef": mock.utr(bank, day, 90),
                        "text": "Bulk NEFT credit for " + " ".join(p["number"] for p in batch) + f" {mock.TAG}", "date": spec["day"]})
    for extra in spec["unmatched"]:
        entries.append({"amountMinor": extra["amountMinor"], "direction": "CRDT", "payment": None, "bankRef": extra["ref"], "text": extra["text"], "date": spec["day"]})
    statement_id = f"MOCK-{bank}-{spec['key']}-{day.strftime('%Y%m%d')}"
    if spec["format"] == "camt053":
        return mock.camt053(statement_id=statement_id, account=spec["account"], bank=bank, day=day, opening_minor=spec["opening"], entries=entries)
    return mock.mt940(statement_id=statement_id, account=spec["account"], day=day, sequence=f"{int(spec['key'][1]):05d}/001", opening_minor=spec["opening"], entries=entries)


def statement_file_name(spec: dict) -> str:
    ext = "xml" if spec["format"] == "camt053" else "sta"
    return f"{spec['format']}_{spec['bank'].lower()}_{spec['day'].replace('-', '')}.{ext}"


def ev_statement(ctx: Ctx, key: str, fmt: str, run_key: str, day: date, account: str) -> None:
    from app.pic.services import bank_files, bank_statement
    marker = f"statement:{key}"
    if F.stage_done(ctx.tenant_id, marker) is not None:
        return
    spec = statement_spec(ctx, key, fmt, run_key, day, account)
    with tenant_tx(ctx.tenant_id) as s:
        pays = {p["number"]: p for p in run_payments(s, spec["run"])}
    text = statement_text(spec, pays)
    with ctx.act(F.TREASURY, ist(day, 18)) as s:
        if key == "S2":
            dry = bank_statement.run_import(s, text.encode("utf-8"), dry_run=True)
            spec["dryRunCounts"] = dry["counts"]
        result = bank_statement.run_import(s, text.encode("utf-8"), dry_run=False)
        spec["importCounts"] = result["counts"]
        spec["credited"], spec["returnedApplied"] = result.get("credited", 0), result.get("returned", 0)
        if spec["ambiguous"]:                                              # treasury enters the UTRs of the bulk credit by hand from the bank portal
            files = [f for f in s.execute(select(PaymentFile).where(PaymentFile.run_ref == spec["run"], PaymentFile.status != "REJECTED")).scalars()]
            if files:
                items = [{"payment": n, "status": "CREDITED", "utr": mock.utr(spec["bank"], day, 90 + i)} for i, n in enumerate(spec["ambiguous"])]
                bank_files.record_bank_results(s, bank_files.by_number(s, files[-1].number, lock=True), items)
                spec["manualCredits"] = len(items)
    ctx.count("bankStatements")
    ctx.plan.setdefault("statements", []).append(spec)
    F.stage_mark(ctx.tenant_id, marker, spec)


def ev_manual_results(ctx: Ctx, key: str, day: date) -> None:
    """Bank portal confirmation keyed by hand (runs without a statement): every payment credited with the bank's UTR."""
    from app.pic.services import bank_files
    marker = f"results:{key}"
    if F.stage_done(ctx.tenant_id, marker) is not None:
        return
    run_ref = _run_ref(ctx, key)
    with ctx.act(F.TREASURY, ist(day, 12)) as s:
        pays = [p for p in run_payments(s, run_ref) if p["status"] == "COMPLETED" and p["bankStatus"] in ("SENT", "NOT_SENT")]
        files = s.execute(select(PaymentFile).where(PaymentFile.run_ref == run_ref, PaymentFile.status != "REJECTED")).scalars().first()
        if files is None or not pays:
            F.stage_mark(ctx.tenant_id, marker, {"credited": 0})
            return
        items = [{"payment": p["number"], "status": "CREDITED", "utr": mock.utr("MANL", day, i)} for i, p in enumerate(pays, start=1)]
        bank_files.record_bank_results(s, bank_files.by_number(s, files.number, lock=True), items)
    ctx.count("manualBankResults", len(items))
    F.stage_mark(ctx.tenant_id, marker, {"credited": len(items)})


def rebuild_statement_files(tenant_id) -> tuple[dict, dict]:
    """Statement files from the specs the pack stored (data/erp_mock/KAC_FINANCE; tools/finance_mock --write / --check)."""
    files, specs = {}, []
    with tenant_tx(tenant_id) as s:
        for key, *_ in STATEMENTS:
            spec = F._stage_done(s, f"statement:{key}")
            if spec is None:
                continue
            pays = {p["number"]: p for p in run_payments(s, spec["run"])}
            files[statement_file_name(spec)] = statement_text(spec, pays)
            specs.append({k: spec[k] for k in ("key", "format", "run", "day", "account", "returned", "ambiguous")})
        plan = F._stage_done(s, "plan") or {}
    return files, {"statements": specs, "planSha256": mock.plan_sha(plan) if plan else None}


# ================================================================================================ credit notes on migrated invoices
def ev_migrated_credit_note(ctx: Ctx, cn: dict) -> None:
    from app.pic.services import payables
    note_no = f"CN-{F.PREFIX}-M{cn['n']:02d}"
    day = day_of(cn["day"])
    with ctx.act(F.AP_APPROVE, ist(day, 14)) as s:
        inv = s.execute(select(Invoice).where(Invoice.number == cn["invoice"])).scalar_one_or_none()
        if inv is None or inv.status != "POSTED" or s.execute(select(CreditNote.id).where(CreditNote.invoice_id == inv.id,
                                                                                           CreditNote.supplier_credit_note_no == note_no)).first():
            return
        line = s.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.line_no)).scalars().first()
        if cn["kind"] == "PRICE":
            entry = {"invoice_line": line.line_no, "qty": str(line.qty), "unit_credit_minor": max(1, int((Decimal(line.unit_price_minor) * Decimal("0.03")).quantize(Decimal(1), ROUND_HALF_UP)))}
        else:
            qty = min(line.qty, max(Decimal(1), (line.qty * Decimal("0.04")).quantize(Decimal(1), ROUND_HALF_UP)))
            entry = {"invoice_line": line.line_no, "qty": str(qty.normalize() if qty == qty.to_integral() else qty)}
        payables.submit_credit_note(s, inv, supplier_credit_note_no=note_no, note_date=day, lines=[entry],
                                    reason=f"MOCK sample: {cn['kind'].lower()} credit note - {CN_TEXT[cn['kind']]}")
    ctx.count("creditNotes")
    ctx.count("migratedCreditNotes")


# ================================================================================================ early payment and SCF
def ev_offer(ctx: Ctx, o: dict) -> None:
    from app.pic.services import early_payment
    day = day_of(o["offer_day"])
    accept = clamp(day + timedelta(days=1))
    with ctx.act(F.AP_CAPTURE, ist(day, 10)) as s:
        inv = s.execute(select(Invoice).where(Invoice.number == o["invoice"])).scalar_one_or_none()
        from app.pic.models import EarlyPaymentOffer
        if (inv is None or inv.status != "POSTED" or inv.payment_status != "UNPAID" or early_payment.live_offer(s, inv) is not None
                or s.execute(select(EarlyPaymentOffer.id).where(EarlyPaymentOffer.invoice_id == inv.id)).first()):
            return
        early_payment.make_offer(s, inv, discount_pct=Decimal(o["pct"]), pay_on=F.RUN_DATE[o["run"]], source=None,
                                 note=f"MOCK sample: dynamic discounting offer, {o['pct']} % for payment on {F.RUN_DATE[o['run']].isoformat()}")
        ctx.count("earlyPaymentOffers")
    email = F.supplier_email(ctx, o["supplier"])
    with ctx.act(email, ist(accept, 15)) as s:
        inv = s.execute(select(Invoice).where(Invoice.number == o["invoice"])).scalar_one()
        live = early_payment.live_offer(s, inv)
        if live is not None and live.status == "OFFERED":
            early_payment.decide(s, inv, live.id, True, "Accepted (MOCK sample)")
            ctx.count("earlyPaymentAccepted")


def ev_scf(ctx: Ctx, o: dict) -> None:
    from app.pic.services import early_payment
    day = day_of(o["day"])
    with ctx.act(F.AP_APPROVE, ist(day, 11)) as s:
        inv = s.execute(select(Invoice).where(Invoice.number == o["invoice"])).scalar_one_or_none()
        from app.pic.models import EarlyPaymentOffer
        if (inv is None or inv.status != "POSTED" or inv.payment_status != "UNPAID" or early_payment.live_offer(s, inv) is not None
                or s.execute(select(EarlyPaymentOffer.id).where(EarlyPaymentOffer.invoice_id == inv.id)).first()):
            return
        early_payment.elect_scf(s, inv, "MOCK sample: supplier elected supply-chain finance through the buyer's programme")
        ctx.count("scfElections")


# ================================================================================================ posting periods
def ev_close(ctx: Ctx, period: str, day: date, reason: str, who: str = F.FC_CLOSE) -> None:
    from app.pic.services import finance_controls
    with ctx.act(who, ist(day, 10)) as s:
        row = s.execute(select(PostingPeriod).where(PostingPeriod.company_code == ctx.spec["company"], PostingPeriod.period == period)).scalar_one_or_none()
        if row is not None and row.status == "CLOSED":
            return
        finance_controls.close_period(s, ctx.spec["company"], period, reason)
    ctx.count("periodsClosed")


def ev_reopen(ctx: Ctx, period: str, day: date, reason: str) -> None:
    from app.pic.services import finance_controls
    marker = f"reopen:{period}"
    if F.stage_done(ctx.tenant_id, marker) is not None:
        return
    with ctx.act(F.FC_CLOSE, ist(day, 10)) as s:
        row = s.execute(select(PostingPeriod).where(PostingPeriod.company_code == ctx.spec["company"], PostingPeriod.period == period)).scalar_one_or_none()
        if row is not None and row.status == "CLOSED":
            finance_controls.reopen_period(s, ctx.spec["company"], period, reason)
            ctx.count("periodsReopened")
    F.stage_mark(ctx.tenant_id, marker, {"period": period})


def ev_reclose(ctx: Ctx, period: str, day: date, reason: str) -> None:
    marker = f"reclose:{period}"
    if F.stage_done(ctx.tenant_id, marker) is not None:
        return
    ev_close(ctx, period, day, reason)
    F.stage_mark(ctx.tenant_id, marker, {"period": period})
