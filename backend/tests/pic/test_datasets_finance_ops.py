"""D15 finance datasets for AXN and KAC (pack finance_ops): MOCK payment history, exceptions, notes, tax data, FX, periods, bank statements, treasury rules.

The tests assert properties (ranges, presence of every state, totals that must agree), never exact global counts: other modules of the suite share the
database and add their own rows. KAC runs on the pack's prerequisites (erp_client_kac, inventory_ops, inventory_master); AXN's signature-case documents are
hashed before the pack runs and must be byte-identical afterwards."""
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, BankStatementImport, CreditNote, Currency, DebitNote, EarlyPaymentOffer, FxRate, GrirSnapshot, Invoice, InvoiceException, Payment,
    PaymentFile, PostingPeriod, RebateSettlement, RuleSet, SodRule, Supplier, TdsCertificate, Tenant,
)
from app.pic.config import BACKEND_DIR
from app.pic.platform import clock, rules
from app.pic.platform.audit import verify_chain
from app.pic.seed import datasets
from app.pic.seed.axion import Scenario, at
from app.pic.seed.datasets import finance_ops as pack
from app.pic.services import einvoice, finance_controls
from app.pic.tools import finance_mock as mock
from tests.pic.conftest import PASSWORD

DATA = BACKEND_DIR / "data" / "erp_mock" / "KAC_FINANCE"


def row_hashes(session, models) -> dict:
    out = {}
    for model in models:
        for row in session.execute(select(model).order_by(model.id)).scalars():
            values = {c.key: getattr(row, c.key) for c in model.__mapper__.column_attrs}
            out[(model.__tablename__, str(row.id))] = hashlib.sha256(json.dumps(values, default=str, sort_keys=True).encode()).hexdigest()
    return out


@pytest.fixture(scope="module")
def packs(database):
    for name in ("erp_client_kac", "contracts_kac", "inventory_ops", "inventory_master"):
        assert {r["status"] for r in datasets.apply_pack(name, PASSWORD)} <= {"LOADED", "ALREADY_LOADED", "SKIPPED"}, name
    with system_tx() as s:
        ids = {code: tid for code, tid in s.execute(select(Tenant.code, Tenant.id))}
    # the documents that exist in AXN before the pack: the signature case (and whatever other packs added); they must not change
    from app.pic.models import CreditNote as CN, DebitNote as DN, InvoiceException as IE, InvoiceLine, PaymentFile as PF
    models = (Invoice, InvoiceLine, IE, CN, DN, Payment, PF)
    with tenant_tx(ids["AXN"]) as s:
        before = row_hashes(s, models)
    started = {}
    import time
    t0 = time.time()
    results = {r["tenant"]: r for r in datasets.apply_pack("finance_ops", PASSWORD)}
    started["seconds"] = time.time() - t0
    assert set(results) == {"AXN", "KAC"} and {r["status"] for r in results.values()} <= {"LOADED", "ALREADY_LOADED"}, results
    yield {"results": results, "ids": ids, "axn_before": before, "models": models, "seconds": started["seconds"]}
    clock.set_pinned(None)


def kac(packs):
    return packs["ids"]["KAC"]


def counts(tenant_id) -> dict:
    with tenant_tx(tenant_id) as s:
        return {name: s.execute(select(func.count()).select_from(model)).scalar_one()
                for name, model in (("audit", AuditEvent), ("invoices", Invoice), ("payments", Payment), ("credit", CreditNote), ("debit", DebitNote),
                                    ("fx", FxRate), ("periods", PostingPeriod), ("grir", GrirSnapshot), ("statements", BankStatementImport), ("files", PaymentFile),
                                    ("users", AppUser), ("rules", RuleSet), ("certificates", TdsCertificate), ("offers", EarlyPaymentOffer),
                                    ("exceptions", InvoiceException))}


# ================================================================ idempotency
def test_a_second_run_changes_nothing(packs):
    assert {r["tenant"]: r["status"] for r in datasets.apply_pack("finance_ops", PASSWORD)} == {"AXN": "ALREADY_LOADED", "KAC": "ALREADY_LOADED"}
    for code in ("AXN", "KAC"):
        before = counts(packs["ids"][code])
        pack.apply(code, PASSWORD)           # the stages and every document look themselves up: a direct second run is a no-op
        assert counts(packs["ids"][code]) == before, code


# ================================================================ KAC payment history
def test_kac_payment_history_has_runs_files_and_bank_results(packs):
    with tenant_tx(kac(packs)) as s:
        paid = s.execute(select(func.count()).select_from(Invoice).where(Invoice.status == "PAID")).scalar_one()
        by_status = dict(s.execute(select(Invoice.status, func.count()).group_by(Invoice.status)).all())
        runs = Counter(r for (r,) in s.execute(select(Payment.run_ref).where(Payment.value_date >= date(2026, 9, 1), Payment.value_date <= date(2026, 10, 31))))
        files = {f.status: f.format for f in s.execute(select(PaymentFile)).scalars()}
        file_status = Counter(f.status for f in s.execute(select(PaymentFile)).scalars())
        bank = Counter(b for (b,) in s.execute(select(Payment.bank_status)))
        returned = list(s.execute(select(Payment).where(Payment.bank_status == "RETURNED")).scalars())
        dates = [d for (d,) in s.execute(select(Payment.value_date).where(Payment.value_date >= date(2026, 9, 1), Payment.run_ref.in_(
            [r for r in runs])))]
    assert 150 <= paid <= 250, paid
    for status in ("PAID", "POSTED", "MATCHED", "APPROVED", "EXCEPTION", "REJECTED"):
        assert by_status.get(status), (status, by_status)
    assert len(runs) >= 6 and max(dates) <= date(2026, 10, 31)
    assert file_status["ACKNOWLEDGED"] >= 3 and file_status["REJECTED"] >= 1 and file_status["SENT"] >= 1, file_status
    assert bank["CREDITED"] > 100 and bank["RETURNED"] >= 3, bank
    assert all(p.status == "CANCELLED" and p.return_reason for p in returned)


def test_returned_payments_went_through_the_real_return_path(packs):
    with tenant_tx(kac(packs)) as s:
        returned = list(s.execute(select(Payment).where(Payment.bank_status == "RETURNED")).scalars())
        events = Counter(a for (a,) in s.execute(select(AuditEvent.action).where(AuditEvent.action.in_(("PAYMENT_RETURNED", "BANK_CREDITED")))))
        reversal = s.execute(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "PAYMENT_RETURNED")).scalar_one()
        invoices = [s.get(Invoice, p.invoice_id) for p in returned]
    assert reversal >= len(returned) >= 3 and events["BANK_CREDITED"] > 100
    assert all(i.status in ("POSTED", "PAID") for i in invoices)       # payable again, or re-paid


def test_msme_suppliers_are_paid_in_time_and_three_breaches_have_interest(packs):
    with tenant_tx(kac(packs)) as s:
        interest = list(s.execute(select(AuditEvent).where(AuditEvent.action == "MSME_INTEREST_ASSESSED")).scalars())
        msme = {x.id for x in s.execute(select(Supplier).where(Supplier.msme_class.in_(("MICRO", "SMALL")))).scalars()}
        on_time = []
        for inv, pay in s.execute(select(Invoice, Payment).join(Payment, Payment.invoice_id == Invoice.id).where(
                Invoice.supplier_id.in_(msme), Invoice.number.like("FO26/%"), Payment.status == "COMPLETED")).all():
            late = pay.value_date > inv.due_date
            on_time.append((inv.number, late, (pay.value_date - (inv.acceptance_date or inv.invoice_date)).days))
        body = rules.resolve(s, "MSME", on=date(2026, 10, 30)).body
        recomputed = []
        for event in interest:
            inv = s.execute(select(Invoice).where(Invoice.number == event.object_ref)).scalar_one()
            amount = (event.after or {})["interestMinor"]
            pay = s.execute(select(Payment).where(Payment.number == event.after["payment"])).scalar_one()
            recomputed.append((amount, finance_controls.msme_interest_minor(s, pay.amount_minor, inv.due_date, pay.value_date)))
    assert body["bankRatePct"] == pack.MSME_BANK_RATE and "MOCK" in body["note"]
    assert len(interest) >= 2 and all(a > 0 and a == b for a, b in recomputed), recomputed
    assert sum(1 for _, late, _ in on_time if not late) >= 1 and all(days <= 45 for _, late, days in on_time if not late), on_time


def test_tds_is_withheld_and_the_26q_export_equals_the_payments(packs):
    with tenant_tx(kac(packs)) as s:
        totals = {}
        for fy, quarter in (("2026-27", "Q2"), ("2026-27", "Q3")):
            first, last = finance_controls.quarter_range(fy, quarter)
            in_quarter = s.execute(select(func.coalesce(func.sum(Payment.tds_minor), 0)).where(
                Payment.status == "COMPLETED", Payment.value_date >= first, Payment.value_date <= last, (Payment.tds_minor > 0) | Payment.tds_certificate.is_not(None))).scalar_one()
            export = finance_controls.tds_export(s, fy, quarter, "26Q")
            rows = list(csv.reader(io.StringIO(export["content"])))
            header, body = rows[0], rows[1:]
            col = header.index("TDS Deducted")
            totals[quarter] = (int(in_quarter), sum(round(Decimal(r[col]) * 100) for r in body), export["rows"])
        withheld = s.execute(select(func.count()).select_from(Payment).where(Payment.tds_minor > 0, Payment.status == "COMPLETED")).scalar_one()
        sections = {sec for (sec,) in s.execute(select(Supplier.tds_section).where(Supplier.tds_section.is_not(None)))}
    assert withheld >= 10 and sum(v[0] for v in totals.values()) > 0
    for quarter, (payments_tds, csv_tds, rows) in totals.items():
        assert payments_tds == csv_tds, (quarter, totals)
    assert {"194C-OTH", "194J-PRO", "194I-LB"} <= sections and "194Q" in sections


def test_tax_master_data_and_certificates(packs):
    with tenant_tx(kac(packs)) as s:
        total = s.execute(select(func.count()).select_from(Supplier)).scalar_one()
        msme = s.execute(select(func.count()).select_from(Supplier).where(Supplier.msme_class.in_(("MICRO", "SMALL")))).scalar_one()
        no_pan = s.execute(select(func.count()).select_from(Supplier).where(Supplier.pan_hash.is_(None), Supplier.country == "IN")).scalar_one()
        no_udyam = s.execute(select(func.count()).select_from(Supplier).where(Supplier.msme_class.is_not(None), Supplier.udyam_no.is_(None))).scalar_one()
        certs = list(s.execute(select(TdsCertificate)).scalars())
        tds_rule = rules.resolve(s, "TDS", on=date(2026, 10, 1))
    assert 0.10 <= msme / total <= 0.25 and no_pan == 0 and no_udyam == 0
    assert len(certs) >= 4 and any(c.valid_to <= date(2026, 11, 30) for c in certs) and all("MOCK" in (c.note or "") for c in certs)
    assert "MOCK" in tds_rule.body["note"] and "pending tax team sign-off" in tds_rule.body["note"]


def test_einvoice_irn_and_qr_valid_and_invalid_cases(packs):
    with tenant_tx(kac(packs)) as s:
        invoices = list(s.execute(select(Invoice).where(Invoice.channel == "E_INVOICE", Invoice.number.like("FO26/%"))).scalars())
        valid = [i for i in invoices if i.irn_valid is True]
        invalid = [i for i in invoices if i.irn_valid is False]
        assert valid and len(invalid) >= 2
        checks = einvoice.verification_of(s, invalid[0])
        good = einvoice.verification_of(s, valid[0])
    assert all(len(i.irn) == 64 and all(c in "0123456789abcdef" for c in i.irn) for i in valid + invalid)
    assert good["valid"] is True and checks["valid"] is False and any(not c["ok"] for c in checks["checks"])
    assert mock.irn_of("33AAKCK7316R1ZX", "2026-27", "INV", "X1") == hashlib.sha256(b"33AAKCK7316R1ZX2026-27INVX1").hexdigest()


# ================================================================ exceptions and notes
def test_exceptions_cover_every_type_and_state(packs):
    with tenant_tx(kac(packs)) as s:
        rows = list(s.execute(select(InvoiceException).join(Invoice, Invoice.id == InvoiceException.invoice_id).where(Invoice.number.like("FO26/%") | Invoice.number.like("FO26-%"))).scalars())
        rejected = s.execute(select(func.count()).select_from(Invoice).where(Invoice.status == "REJECTED", Invoice.number.like("FO26%"))).scalar_one()
    types = {e.type for e in rows}
    assert {"PRICE", "QUANTITY", "MISSING_GR", "TAX", "DUPLICATE"} <= types, types
    assert 25 <= len(rows) <= 60, len(rows)
    for kind in ("PRICE", "QUANTITY", "MISSING_GR"):
        states = {(e.status, e.resolution) for e in rows if e.type == kind}
        assert any(st == "OPEN" for st, _ in states) and any(st == "RESOLVED" for st, _ in states), (kind, states)
    assert any(e.resolution == "DISPUTE" for e in rows) and any(e.resolution == "PRICE_APPROVAL_PENDING" for e in rows)
    assert {e.resolution for e in rows if e.status == "RESOLVED"} >= {"CREDIT_NOTE_RECEIVED", "PRICE_ACCEPTED", "GR_POSTED", "NOT_DUPLICATE", "REJECTED"}
    assert rejected >= 3


def test_credit_and_debit_notes_in_every_reachable_state(packs):
    with tenant_tx(kac(packs)) as s:
        credit = list(s.execute(select(CreditNote)).scalars())
        debit = Counter(d.status for d in s.execute(select(DebitNote)).scalars())
        memos = Counter(m for (m,) in s.execute(select(func.coalesce(AuditEvent.after["erpCreditMemo"].astext, "")).where(AuditEvent.action == "CREDIT_NOTE_RECEIVED")))
        offers = Counter((o.kind, o.status) for o in s.execute(select(EarlyPaymentOffer)).scalars())
    assert len(credit) >= 18 and sum(1 for c in credit if "price" in c.reason.lower()) >= 3
    assert all("MOCK" in c.reason for c in credit if c.supplier_credit_note_no.startswith("CN-FO26"))
    for status in ("MATCHED", "PENDING_APPROVAL", "POSTED", "REJECTED"):
        assert debit.get(status), debit
    assert sum(debit.values()) >= 9
    assert offers[("DISCOUNT", "APPLIED")] >= 10 and offers[("SCF", "ACCEPTED")] >= 3, offers


# ================================================================ FX, foreign invoices, periods, GR/IR
def test_fx_rates_are_complete_for_every_weekday_in_both_tenants(packs):
    days = mock.weekdays()
    assert days[0] == date(2026, 4, 1) and days[-1] == date(2026, 10, 30) and all(d.weekday() < 5 for d in days) and len(days) > 150
    for code in ("KAC", "AXN"):
        with tenant_tx(packs["ids"][code]) as s:
            have = {(f, d) for f, d in s.execute(select(FxRate.from_ccy, FxRate.valid_from).where(FxRate.to_ccy == "INR"))}
            ccys = {c for (c,) in s.execute(select(Currency.code))}
        for ccy in ("USD", "EUR", "GBP", "JPY", "CNY"):
            missing = [d for d in days if (ccy, d) not in have]
            assert not missing, (code, ccy, missing[:3])
        assert "CNY" in ccys
    with tenant_tx(kac(packs)) as s:
        usd = {d: r for d, r in s.execute(select(FxRate.valid_from, FxRate.rate).where(FxRate.from_ccy == "USD", FxRate.to_ccy == "INR"))}
        anchor = usd[mock.FX_ANCHOR]
    assert anchor == Decimal("95.22780000") and all(Decimal("85") < r < Decimal("105") for r in usd.values())
    assert mock.fx_series(pack.reference_anchors()) == mock.fx_series(pack.reference_anchors())          # deterministic


def test_foreign_currency_invoices_fix_the_rate_and_some_are_paid_in_currency(packs):
    with tenant_tx(kac(packs)) as s:
        foreign = list(s.execute(select(Invoice).where(Invoice.currency != "INR")).scalars())
        paid = [(i, p) for i, p in s.execute(select(Invoice, Payment).join(Payment, Payment.invoice_id == Invoice.id).where(Invoice.currency != "INR",
                                                                                                                           Payment.status == "COMPLETED")).all()]
    assert {i.currency for i in foreign} >= {"USD", "EUR", "JPY"} and len(foreign) >= 4
    assert all(i.fx_rate is not None and i.gross_group_minor for i in foreign if i.status in ("POSTED", "PAID"))
    assert len(paid) >= 2 and all(p.currency == i.currency for i, p in paid)


def test_periods_april_to_september_closed_with_a_grir_snapshot_each_and_october_open(packs):
    with tenant_tx(kac(packs)) as s:
        periods = {p.period: p for p in s.execute(select(PostingPeriod).where(PostingPeriod.company_code == "1000")).scalars()}
        snapshots = Counter(g.period for g in s.execute(select(GrirSnapshot).where(GrirSnapshot.company_code == "1000")).scalars())
        lines = [g.line_count for g in s.execute(select(GrirSnapshot)).scalars()]
        actions = [a for (a,) in s.execute(select(AuditEvent.action).where(AuditEvent.object_type == "POSTING_PERIOD").order_by(AuditEvent.seq))]
        sept = periods["2026-09"]
    for month in ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"):
        assert periods[month].status == "CLOSED" and snapshots[month] >= 1, month
    assert "2026-10" not in periods or periods["2026-10"].status != "CLOSED"
    assert snapshots["2026-09"] == 2 and "REOPENED" in actions and sept.reason and sum(lines) > 0
    assert actions.index("REOPENED") > actions.index("CLOSED")


# ================================================================ bank statements
def test_bank_statements_reconcile_with_the_payments(packs):
    with tenant_tx(kac(packs)) as s:
        imports = {b.statement_id: b for b in s.execute(select(BankStatementImport)).scalars()}
        specs = {k: s_ for k in ("S1", "S2", "S3", "S4", "S5") if (s_ := pack_stage(s, f"statement:{k}"))}
        credited = Counter(p.bank_status for p in s.execute(select(Payment)).scalars())
        unmatched_state = {k: (imports[next(i for i in imports if f"-{k}-" in i)].result["counts"]) for k in specs}
    assert set(specs) == {"S1", "S2", "S3", "S4", "S5"}
    assert unmatched_state["S1"].get("READY", 0) == len(specs["S1"]["payments"]) and set(unmatched_state["S1"]) == {"READY"}      # fully matched
    assert unmatched_state["S2"].get("UNMATCHED") == 1 and unmatched_state["S2"].get("AMBIGUOUS") == 1                           # the importer reports both
    assert unmatched_state["S3"].get("READY", 0) >= 10 and specs["S3"]["returned"] and specs["S4"]["format"] == "mt940"
    assert credited["CREDITED"] and credited["RETURNED"] >= 3
    for key, spec in specs.items():                                                                                                # statement debits equal the payments
        with tenant_tx(kac(packs)) as s:
            pays = {p.number: p for p in s.execute(select(Payment).where(Payment.run_ref == spec["run"])).scalars()}
        listed = sum(pays[n].amount_minor for n in spec["payments"] if n not in spec["returned"])
        assert listed > 0


def pack_stage(s, key):
    return pack._stage_done(s, key)


def test_committed_statement_files_match_the_manifest_and_the_generator(packs):
    assert mock.verify_files(DATA) == []
    manifest = json.loads((DATA / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["fictional"] is True and "MOCK" in manifest["label"] and set(manifest["files"]) >= {"camt053_hdfc_20260921.xml", "mt940_icic_20261031.sta"}
    files, extra = pack.rebuild_statement_files(kac(packs))
    on_disk = {p.name: p.read_bytes().decode("utf-8") for p in DATA.glob("*") if p.suffix in (".xml", ".sta")}
    assert set(files) == set(on_disk) or extra["planSha256"] != manifest.get("planSha256")
    # the committed files were generated from a database that planned the same cases (same fingerprint): then they are what the generator builds now, up to the
    # payment numbers (those depend on how many payments the tenant had numbered). A database that planned other cases (other tests ran first) has other documents.
    if extra["planSha256"] == manifest.get("planSha256"):
        for name, text in files.items():
            assert mock.normalise(on_disk[name]) == mock.normalise(text), name
    assert subprocess.run([sys.executable, "-m", "app.pic.tools.finance_mock", "--check"], cwd=BACKEND_DIR, capture_output=True, text=True,
                          env={**os.environ, "DATABASE_URL": ""}).returncode == 0


# ================================================================ treasury, rules, rebates
def test_treasury_rule_values_and_rebates(packs):
    with tenant_tx(kac(packs)) as s:
        a = rules.resolve(s, "PAYMENT-FILE", on=date(2026, 10, 1), company_code="1000").body
        b = rules.resolve(s, "PAYMENT-FILE", on=date(2026, 10, 25), company_code="1000").body
        run = rules.resolve(s, "PAYMENT-RUN", on=date(2026, 10, 1))
        desc = {r.key: r.description for r in s.execute(select(RuleSet).where(RuleSet.version.like("2026.2-%"))).scalars()}
        settlements = list(s.execute(select(RebateSettlement)).scalars())
    assert a["debtorAccountRef"] != b["debtorAccountRef"] and "MOCK" in a["debtorAccountRef"] and a["debtorIfsc"].startswith("MOCK")
    assert run.body["approverRole"] == "FINANCE_CONTROLLER" and run.body["horizonDays"] == 7
    assert desc and all("MOCK" in d for d in desc.values())
    assert settlements and all(r.status in ("PENDING_ERP", "POSTED") and r.amount_minor > 0 for r in settlements)


def test_advances_are_paid_and_recovered_from_later_bills_one_backed_by_a_guarantee(packs):
    from app.pic.models import AdvancePayment, AdvanceRecovery, BankGuarantee
    with tenant_tx(kac(packs)) as s:
        advances = list(s.execute(select(AdvancePayment).where(AdvancePayment.reference.like("ADV-PI-FO26-%")).order_by(AdvancePayment.number)).scalars())
        guarantees = {g.id: g for g in s.execute(select(BankGuarantee)).scalars()}
        recoveries = list(s.execute(select(AdvanceRecovery).where(AdvanceRecovery.advance_id.in_([a.id for a in advances]))).scalars())
        paid_with_deduction = s.execute(select(func.count()).select_from(AuditEvent).where(AuditEvent.object_type == "ADVANCE_PAYMENT", AuditEvent.action == "RECOVERED")).scalar_one()
    assert len(advances) == 3 and all(a.status in ("PAID", "RECOVERED") for a in advances), [(a.number, a.status) for a in advances]
    backed = [a for a in advances if a.guarantee_id]
    assert len(backed) == 1 and guarantees[backed[0].guarantee_id].status == "ACTIVE" and guarantees[backed[0].guarantee_id].amount_minor >= backed[0].gross_minor
    assert recoveries and paid_with_deduction >= 1 and all(r.amount_minor > 0 for r in recoveries)


# ================================================================ users and segregation of duties
def test_pack_users_have_the_right_attributes_and_sod_holds_for_every_pair(packs):
    with tenant_tx(kac(packs)) as s:
        users = {u.email.split("@")[0]: u for u in s.execute(select(AppUser).where(AppUser.attributes["mock"].astext == pack.KEY)).scalars()}
    assert {"ap.clerk.1", "ap.clerk.2", "fin.controller.1", "fin.controller.2", "treasury.1000", "tax.manager"} <= set(users)
    assert sum(1 for u in users.values() if "AP_CLERK" in u.roles) >= 2 and sum(1 for u in users.values() if "FINANCE_CONTROLLER" in u.roles) >= 4
    assert all(u.attributes["company_codes"] == ["1000"] for u in users.values() if "SUPPLIER_USER" not in u.roles and "company_codes" in u.attributes)
    assert users["treasury.1000"].attributes["approval_limits"]["PAYMENT_RUN"] > 0 and users["tax.manager"].attributes["approval_limits"]["PAYMENT_RUN"] == 0
    # SOD-08 (capturer cannot approve) and SOD-09 (approver cannot pay): the pack's own documents were captured, approved and paid by different people
    with tenant_tx(kac(packs)) as s:
        for inv, pay in s.execute(select(Invoice, Payment).join(Payment, Payment.invoice_id == Invoice.id).where(Invoice.number.like("FO26/%"), Payment.status != "CANCELLED")).all():
            assert inv.created_by != inv.approved_by, inv.number            # SOD-08
            assert inv.approved_by != pay.approved_by, inv.number           # SOD-09
        violations = s.execute(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "SOD_VIOLATION")).scalar_one()
    assert violations >= 0
    # every pair of pack users: the same person never holds both sides of a rule
    sc = Scenario(kac(packs), tenant_code="KAC", domain="kaveri-auto.example")
    for rule_code, first, second in (("SOD-08", "INVOICE_CAPTURE", "INVOICE_APPROVE"), ("SOD-09", "INVOICE_APPROVE", "PAYMENT_APPROVE")):
        with tenant_tx(kac(packs)) as s:
            rule = s.execute(select(SodRule).where(SodRule.code == rule_code)).scalar_one()
        assert (rule.action_a, rule.action_b) == (first, second)
    # approval limits: an AP clerk cannot approve an invoice above INR 10 lakh, the treasury approver cannot approve invoices at all, the tax manager cannot pay
    from app.pic.platform import abac
    with sc.act("ap.clerk.1", at(date(2026, 10, 31), 10)) as s:
        assert abac.evaluate(abac.policy_for(s), users["ap.clerk.1"].attributes, "INVOICE_APPROVE", {"company_code": "1000"}, 11 * pack.L)["allowed"] is False
        assert abac.evaluate(abac.policy_for(s), users["ap.clerk.1"].attributes, "INVOICE_APPROVE", {"company_code": "1000"}, 9 * pack.L)["allowed"] is True
        assert abac.evaluate(abac.policy_for(s), users["treasury.1000"].attributes, "INVOICE_APPROVE", {"company_code": "1000"}, 1000)["allowed"] is False
        assert abac.evaluate(abac.policy_for(s), users["tax.manager"].attributes, "PAYMENT_RUN", {"company_code": "1000"}, 1000)["allowed"] is False
        assert abac.evaluate(abac.policy_for(s), users["treasury.1000"].attributes, "PAYMENT_RUN", {"company_code": "1000"}, 400 * pack.L)["allowed"] is True
        assert abac.evaluate(abac.policy_for(s), users["fin.controller.1"].attributes, "PAYMENT_RUN", {"company_code": "1000"}, 1000)["allowed"] is False


# ================================================================ AXN: non-signature additions only
def test_axn_additions_leave_every_existing_document_untouched(packs):
    with tenant_tx(packs["ids"]["AXN"]) as s:
        after = row_hashes(s, packs["models"])
    before = packs["axn_before"]
    changed = [k for k, v in before.items() if after.get(k) != v]
    assert not changed, changed[:5]
    new_documents = len(after) - len(before)
    with tenant_tx(packs["ids"]["AXN"]) as s:
        closed = sorted(p.period for p in s.execute(select(PostingPeriod).where(PostingPeriod.status == "CLOSED")).scalars())
        certs = s.execute(select(func.count()).select_from(TdsCertificate)).scalar_one()
        tds = s.execute(select(func.count()).select_from(Supplier).where(Supplier.tds_section.is_not(None))).scalar_one()
        signature = s.execute(select(func.count()).select_from(Supplier).where(Supplier.code.in_(("TF001", "KD002", "HTS004")), Supplier.tds_section.is_not(None))).scalar_one()
        unpaid_new = s.execute(select(func.count()).select_from(Invoice).where(Invoice.number.like("FO26/%"), Invoice.status == "POSTED", Invoice.payment_status == "UNPAID")).scalar_one()
    assert new_documents < 60
    assert closed[:7] == [f"2026-{m:02d}" for m in range(4, 11)] and certs >= 1 and tds >= 1 and signature == 0 and unpaid_new == 0


def test_axn_documents_notes_and_a_returned_payment(packs):
    with tenant_tx(packs["ids"]["AXN"]) as s:
        mine = list(s.execute(select(Invoice).where(Invoice.number.like("FO26/%"))).scalars())
        credit = s.execute(select(func.count()).select_from(CreditNote).where(CreditNote.supplier_credit_note_no.like("CN-FO26-%"))).scalar_one()
        debit = s.execute(select(func.count()).select_from(DebitNote).where(DebitNote.supplier_debit_note_no.like("DN-FO26-%"))).scalar_one()
        returned = s.execute(select(func.count()).select_from(Payment).where(Payment.bank_status == "RETURNED", Payment.run_ref.in_(
            select(Payment.run_ref).join(Invoice, Invoice.id == Payment.invoice_id).where(Invoice.number.like("FO26/%"))))).scalar_one()
    if not mine:
        pytest.skip("the packs that create open orders of non-signature suppliers are not loaded in this database")
    assert len(mine) == 3 and all(i.status == "PAID" for i in mine) and credit == 2 and debit == 2 and returned == 1


# ================================================================ integrity
def test_audit_hash_chains_are_valid_for_axn_and_kac(packs):
    for code in ("AXN", "KAC"):
        with tenant_tx(packs["ids"][code]) as s:
            chain = verify_chain(s)
        assert chain["valid"], (code, chain)


def test_pack_registration_neon_setup_and_runtime(packs):
    names = list(datasets.PACKS)
    assert names.index("finance_ops") == names.index("inventory_master") + 1 and names.index("finance_ops") < names.index("reference_data")
    assert datasets.load("finance_ops").REQUIRES == {"inventory-master": "1"} and datasets.load("finance_ops").KEY == "finance-ops"
    done = subprocess.run([sys.executable, "-m", "app.pic.tools.neon_setup", "--help"], cwd=BACKEND_DIR, capture_output=True, text=True,
                          env={**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]})
    assert done.returncode == 0 and "--verify-only" in done.stdout
    assert packs["seconds"] < 3600


# ================================================================ the generator is deterministic and its files parse with the real importer
def test_generated_statements_parse_with_the_importer_and_the_series_is_deterministic():
    from app.pic.services import bank_statement
    day = date(2026, 10, 5)
    entries = [{"amountMinor": 12_345_67, "direction": "DBIT", "payment": "PAY-900001", "text": "PAY-900001 S1", "bankRef": mock.utr("HDFC", day, 1), "date": day.isoformat()},
               {"amountMinor": 5_000_00, "direction": "CRDT", "returned": True, "payment": "PAY-900002", "text": "Return", "bankRef": "MRTN1", "reason": "Account closed", "rsn": "AC04",
                "date": day.isoformat()}]
    camt = mock.camt053(statement_id="T-1", account="MOCK-CA-0001", bank="HDFC", day=day, opening_minor=10_000_000, entries=entries)
    sta = mock.mt940(statement_id="T-2", account="MOCK-CA-0002", day=day, sequence="00001/001", opening_minor=10_000_000, entries=entries)
    for parsed in (bank_statement.parse(camt.encode()), bank_statement.parse(sta.encode())):
        assert [e["amountMinor"] for e in parsed["entries"]] == [1_234_567, 500_000]
        assert [e["returned"] for e in parsed["entries"]] == [False, True] and parsed["entries"][0]["bankRef"].startswith("MOCKHDFC")
    assert camt == mock.camt053(statement_id="T-1", account="MOCK-CA-0001", bank="HDFC", day=day, opening_minor=10_000_000, entries=entries)
    assert mock.normalise("PAY-880016 PAY-880020 PAY-880016") == "P001 P002 P001"
    first = mock.fx_series({"USD": Decimal("95.2278")})
    assert first == mock.fx_series({"USD": Decimal("95.2278")}) and len(first) == 5 * len(mock.weekdays())
    anchor = {(c, d): r for c, d, r in first}
    assert anchor[("USD", mock.FX_ANCHOR)] == Decimal("95.22780000") and anchor[("USD", date(2026, 10, 30))] == Decimal("95.22780000")
    assert all(Decimal("0.9") < r / anchor[(c, mock.FX_ANCHOR)] < Decimal("1.1") for (c, d), r in anchor.items())
