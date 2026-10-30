"""D10 ERP client migration: tenant KAC loaded from the mock SAP S/4HANA extract (TD §12.4, MIG-1..5).

Generator determinism, extract integrity, every deliberate reject, load counts, idempotency, the GL tie-out with its documented
variances, a delta extract, and the business after cutover: an open PO received and invoiced through the services, an open
AP item paid by a payment run limited to its supplier, and the spend overview over the loaded history.
"""
import csv
import hashlib
import json
import shutil
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AuditEvent, Contract, ContractLine, ErpDocument, Invoice, Material, MaverickHit, Payment, PoLine, PriceValidity, PurchaseOrder, SpendLine,
    Supplier, SupplierBankAccount, Tenant, Timer,
)
from app.pic.platform import clock, crypto
from app.pic.seed import datasets
from app.pic.seed.axion import Scenario, at
from app.pic.seed.datasets import erp_client_kac as pack
from app.pic.tools import erp_load, erp_mock
from tests.pic.conftest import PASSWORD

DATA = erp_mock.OUT_DIR


@pytest.fixture(scope="module")
def loaded(database):
    results = datasets.apply_pack("erp_client_kac", PASSWORD)
    assert [r["status"] for r in results] == ["LOADED"], results
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == "KAC")).scalar_one()
    yield {"summary": results[0]["summary"]["load"], "tenant_id": tenant_id, "sc": Scenario(tenant_id, "KAC", pack.DOMAIN, pack.ROLE_USER)}
    clock.set_pinned(None)


def _edit_csv(path, lifnr, column, value):
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    index = rows[0].index(column)
    for row in rows[1:]:
        if row[0] == lifnr:
            row[index] = value
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\n").writerows(rows)


def _keys(summary, obj, reason):
    return sorted(r["key"] for r in summary["rejects"]["rows"] if r["object"] == obj and r["reason"] == reason)


# ---------------------------------------------------------------- the extract
def test_generator_is_deterministic(tmp_path):
    manifest = erp_mock.generate(tmp_path / "KAC")
    committed = json.loads((DATA / "MANIFEST.json").read_text(encoding="utf-8"))
    assert {k: v["sha256"] for k, v in manifest["files"].items()} == {k: v["sha256"] for k, v in committed["files"].items()}
    for name, entry in committed["files"].items():
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == entry["sha256"], name
    assert sum((DATA / n).stat().st_size for n in committed["files"]) < 15_000_000


def test_extract_integrity_is_checked(tmp_path):
    copy = tmp_path / "KAC"
    shutil.copytree(DATA, copy)
    path = copy / "LFA1.csv"
    path.write_bytes(path.read_bytes().replace(b"Pvt Ltd", b"Pvt. Ltd", 1))
    with pytest.raises(erp_load.ExtractError, match="SHA-256"):
        erp_load.read_extract(copy)
    (copy / "LFA1.csv").unlink()
    with pytest.raises(erp_load.ExtractError, match="missing"):
        erp_load.read_extract(copy)


def test_mock_data_is_fictional_and_tax_ids_are_valid():
    extract = erp_load.read_extract(DATA)
    from app.pic.services.master_changes import gstin_errors
    rejected = {"200301", "200302", "200303", "200304", "200305"}
    for r in extract.rows("LFA1"):
        if erp_load.alpha(r["LIFNR"]) not in rejected:
            assert gstin_errors(r["STCD3"], r["J_1IPANNO"]) == [], r["LIFNR"]
    assert all(r["SMTP_ADDR"].endswith(".example") and not r["TEL_NUMBER"] for r in extract.rows("ADRC"))
    assert all(r["BANKL"][4:6] == "0K" for r in extract.rows("LFBK"))     # fictional branch codes
    entries = erp_load.hsn_master()
    for r in extract.rows("MARC"):
        if r["STEUC"] and r["STEUC"] != "999999":
            assert erp_load.gst_lookup(entries, r["STEUC"]), r["STEUC"]


def test_validate_only_writes_nothing():
    summary = erp_load.load("NO-SUCH-TENANT", DATA, validate_only=True)
    assert summary["validateOnly"] and summary["audit"] == {}
    spend = summary["tieOut"]["spend"]
    assert spend["byStatus"] == {"BALANCED": 21, "EXPLAINED": 2, "UNEXPLAINED": 1}
    with pytest.raises(erp_load.ExtractError, match="does not exist"):
        erp_load.load("NO-SUCH-TENANT", DATA)


# ---------------------------------------------------------------- validation rejects
def test_every_deliberate_error_is_rejected_with_its_reason(loaded):
    s = loaded["summary"]
    assert _keys(s, "vendors", "GSTIN_MISSING") == ["200301", "200302"]
    assert _keys(s, "vendors", "GSTIN_INVALID") == ["200303", "200305"]
    assert _keys(s, "vendors", "GSTIN_PAN_MISMATCH") == ["200304"]
    assert _keys(s, "vendorBanks", "BANK_IFSC_INVALID") == ["200081"]
    assert _keys(s, "materials", "HSN_MISSING") == ["41000198", "41000199"]
    assert _keys(s, "materials", "HSN_UNKNOWN") == ["41000200"]
    assert _keys(s, "materials", "UOM_UNKNOWN") == ["41000197"]
    assert _keys(s, "materials", "MATERIAL_GROUP_UNMAPPED") == ["41000196"]
    assert _keys(s, "agreements", "VALIDITY_INVALID") == ["5500000999"]
    reasons = s["rejects"]["byReason"]
    assert reasons["spendLines"]["QTY_NEGATIVE"] == 3 and reasons["spendLines"]["MATERIAL_UNKNOWN"] == 2
    assert reasons["spendLines"]["PO_UNKNOWN"] == 1 and reasons["spendLines"]["DUPLICATE_KEY"] == 1
    assert reasons["openPoLines"] == {"MATERIAL_UNKNOWN": 1, "PRICE_INVALID": 1, "QTY_INVALID": 1, "VENDOR_NOT_LOADED": 1}
    duplicate = [r for r in s["rejects"]["rows"] if r["reason"] == "DUPLICATE_INVOICE"]
    assert len(duplicate) == 1 and "of 100074" in duplicate[0]["detail"] and duplicate[0]["key"] == "5105690001/2026"
    # every reject of a vendor-dependent object points at one of the five rejected vendors
    assert all(any(v in r["detail"] for v in ("200301", "200302", "200303", "200304", "200305"))
               for r in s["rejects"]["rows"] if r["reason"] == "VENDOR_NOT_LOADED")


# ---------------------------------------------------------------- what was loaded
def test_load_counts_match_the_database(loaded):
    s, objects = loaded["summary"], loaded["summary"]["objects"]
    with tenant_tx(loaded["tenant_id"]) as db:
        def count(model, *where):
            return db.execute(select(func.count()).select_from(model).where(*where)).scalar()
        assert count(Supplier) == objects["vendors"]["loaded"] == objects["vendors"]["extract"] - 5
        assert count(SupplierBankAccount) == objects["vendorBanks"]["loaded"]
        assert count(Material) == objects["materials"]["loaded"] == objects["materials"]["extract"] - 5 - objects["materials"]["skipped"]
        assert count(Contract, Contract.status == "ACTIVE") == objects["agreements"]["loaded"] == 40
        assert count(PriceValidity) > 40
        assert count(PurchaseOrder, PurchaseOrder.erp_doc_no.is_not(None)) == objects["openPos"]["loaded"]
        assert count(PoLine) == objects["openPoLines"]["loaded"] == objects["openPoLines"]["extract"] - 4
        assert count(Invoice, Invoice.channel == "ERP_MIGRATION") == objects["openAp"]["loaded"] == objects["openAp"]["extract"] - 5
        assert count(SpendLine, SpendLine.source == "ERP_HISTORY") == objects["spendLines"]["loaded"] == objects["spendLines"]["extract"] - 70
        assert 240 <= objects["vendors"]["extract"] <= 260 and 1100 <= objects["materials"]["extract"] <= 1300
        assert objects["spendLines"]["extract"] > 25000 and objects["openPoLines"]["extract"] >= 300
        # bank account and GSTIN are field-encrypted
        vendor = db.execute(select(Supplier).where(Supplier.code == "100001")).scalar_one()
        account = db.execute(select(SupplierBankAccount).where(SupplierBankAccount.supplier_id == vendor.id)).scalar_one()
        lfbk = next(r for r in erp_load.read_extract(DATA).rows("LFBK") if r["LIFNR"] == "0000100001")
        assert crypto.decrypt(loaded["tenant_id"], "bank", account.account_enc) == lfbk["BANKN"] and lfbk["BANKN"] not in account.account_masked
        assert crypto.decrypt(loaded["tenant_id"], "gstin", vendor.gstin_enc).startswith(vendor.state_code)
        assert db.execute(select(Supplier.status).where(Supplier.code == "100012")).scalar() == "BLOCKED"
        assert db.execute(select(Supplier.status).where(Supplier.code == "100019")).scalar() == "BLOCKED"   # deletion flag: history only
        # audited as INITIAL_LOAD by integration:SAP_S4
        events = db.execute(select(AuditEvent).where(AuditEvent.tenant_id == loaded["tenant_id"], AuditEvent.action == "INITIAL_LOAD")).scalars().all()
        assert {e.after["object"] for e in events} >= {"org", "vendors", "materials", "infoRecords", "sourceLists", "agreements", "openPos",
                                                       "openAp", "spendLines"}
        assert {e.actor for e in events} == {"integration:SAP_S4"}
        assert db.execute(select(AuditEvent.actor).where(AuditEvent.object_id == vendor.id, AuditEvent.action == "MIGRATED")).scalar() == "integration:SAP_S4"
        # contracts carry renewal and expiry timers, price validities from the ERP conditions and consumption so far
        contract = db.execute(select(Contract).where(Contract.type == "SCHEDULING_AGREEMENT").order_by(Contract.number)).scalars().first()
        assert {t.kind for t in db.execute(select(Timer).where(Timer.object_id == contract.id)).scalars()} == {"CONTRACT_RENEWAL", "CONTRACT_EXPIRY"}
        assert sum(l.released_qty for l in db.execute(select(ContractLine).where(ContractLine.contract_id == contract.id)).scalars()) > 0
    assert s["audit"] == {k: "INITIAL_LOAD" for k in s["audit"]}


def test_duplicate_scan_flags_the_mdm_candidates(loaded):
    with tenant_tx(loaded["tenant_id"]) as db:
        screening = {x.code: x.screening for x in db.execute(select(Supplier)).scalars()}
    def reasons(code):
        return {(d["code"], d["reason"]) for d in screening[code].get("duplicates") or []}
    assert ("100031", "same GSTIN") in reasons("100198") and screening["100198"]["outcome"] == "REVIEW"
    assert any(c == "100047" and r.startswith("same PAN") for c, r in reasons("100211"))
    assert ("200201", "similar legal name") in reasons("200202")
    assert screening["200203"]["bankDuplicates"] == ["200052"] and screening["200203"]["outcome"] == "REVIEW"
    assert {d["supplier"] for d in loaded["summary"]["duplicates"]} >= {"100198", "100211", "200202", "200203", "200052"}
    assert len(loaded["summary"]["bankVerificationSample"]) >= 10


# ---------------------------------------------------------------- tie-out
def test_tie_out_balances_except_the_documented_variances(loaded):
    tie = loaded["summary"]["tieOut"]
    status = {p["period"]: p["status"] for p in tie["spend"]["periods"]}
    assert len(status) == 24 and status.pop("2025-03") == "EXPLAINED" and status.pop("2026-09") == "EXPLAINED"
    assert status.pop("2026-08") == "UNEXPLAINED"
    assert set(status.values()) == {"BALANCED"}
    by_period = {p["period"]: p for p in tie["spend"]["periods"]}
    assert by_period["2025-03"]["reconcilingItemsMinor"] == 42_00_000 * 100
    assert by_period["2026-08"]["unexplainedMinor"] == 24_60_000 * 100
    assert abs(Decimal(tie["spend"]["totals"]["differencePct"])) <= Decimal("0.5")
    assert all(abs(Decimal(p["differencePct"])) <= Decimal("0.5") for p in tie["spend"]["periods"] if p["status"] == "BALANCED")
    assert tie["openAp"]["extractMatchesGl"] and tie["openAp"]["loadedPlusRejectedMatchesGl"]
    assert tie["openPo"]["differences"] and all(d["explainedByRejects"] for d in tie["openPo"]["differences"])
    assert tie["contracts"]["activeInExtract"] == tie["contracts"]["loaded"] == 40


def test_second_load_is_idempotent(loaded):
    assert datasets.apply_pack("erp_client_kac", PASSWORD)[0]["status"] == "ALREADY_LOADED"
    with tenant_tx(loaded["tenant_id"]) as db:
        before = db.execute(select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == loaded["tenant_id"])).scalar()
        spend_before = db.execute(select(func.count()).select_from(SpendLine)).scalar()
    again = erp_load.load("KAC", DATA, when=at(date(2026, 11, 1), 8))
    assert all(v.get("loaded", 0) == 0 for k, v in again["objects"].items()), again["objects"]
    assert again["objects"]["spendLines"]["existing"] == spend_before and again["audit"] == {}
    with tenant_tx(loaded["tenant_id"]) as db:
        assert db.execute(select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == loaded["tenant_id"])).scalar() == before
    assert again["tieOut"]["spend"]["byStatus"] == loaded["summary"]["tieOut"]["spend"]["byStatus"]


# ---------------------------------------------------------------- business after cutover
def test_open_po_is_received_and_invoiced_through_the_services(loaded):
    from app.pic.services import payables, receiving
    sc = loaded["sc"]
    receivers = {"1100": "receiver.hosur", "1200": "receiver.oragadam", "1300": "receiver.bidadi"}
    with tenant_tx(loaded["tenant_id"]) as db:
        line, po = db.execute(select(PoLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
                              .where(PoLine.gr_required.is_(True), PoLine.quality_managed.is_(False), PoLine.purchase_type == "STOCK",
                                     PoLine.received_qty == 0, Supplier.status == "ACTIVE", PurchaseOrder.status == "CONFIRMED")
                              .order_by(PurchaseOrder.erp_doc_no, PoLine.line_no)).first()
        po_id, po_number, line_no, qty, price, erp, plant = po.id, po.number, line.line_no, line.qty, line.unit_price_minor, po.erp_doc_no, line.plant
        supplier = db.get(Supplier, po.supplier_id).code
    with sc.act(receivers[plant], at(date(2026, 11, 3), 11)) as s:
        gr = receiving.post_gr(s, s.get(PurchaseOrder, po_id), lines=[{"line": line_no, "qty": str(qty)}], delivery_note=f"DN-{erp}")
        assert gr.status in ("POSTED", "COMPLETED", "ACCEPTED")
    with sc.act("ap.clerk", at(date(2026, 11, 4), 10)) as s:
        invoice = payables.capture(s, supplier=supplier, supplier_invoice_no=f"KAC-TEST/{erp}", invoice_date=date(2026, 11, 3), channel="PDF_OCR",
                                   lines=[{"po": po_number, "po_line": line_no, "qty": str(qty), "unit_price": str(Decimal(price) / 100)}])
        assert invoice.status == "MATCHED", invoice.status
        payables.approve(s, invoice)
        result = payables.post(s, invoice, None)
        assert result["status"] == "POSTED" and result["erpDocument"]
    with tenant_tx(loaded["tenant_id"]) as db:
        assert db.get(PurchaseOrder, po_id).status in ("RECEIVED", "INVOICED", "PARTIALLY_RECEIVED")
        assert db.execute(select(PoLine.invoiced_qty).where(PoLine.po_id == po_id, PoLine.line_no == line_no)).scalar() == qty


def test_open_ap_item_is_paid_by_a_payment_run_for_its_supplier(loaded):
    from app.pic.services import payables
    sc = loaded["sc"]
    with tenant_tx(loaded["tenant_id"]) as db:
        invoice = db.execute(select(Invoice).join(Supplier, Supplier.id == Invoice.supplier_id)
                             .join(SupplierBankAccount, SupplierBankAccount.supplier_id == Supplier.id)
                             .where(Invoice.channel == "ERP_MIGRATION", Invoice.payment_block.is_(False), Supplier.status == "ACTIVE",
                                    SupplierBankAccount.active.is_(True)).order_by(Invoice.due_date, Invoice.number)).scalars().first()
        number, due, supplier_id = invoice.number, invoice.due_date, invoice.supplier_id
        code = db.get(Supplier, supplier_id).code
        others_unpaid = db.execute(select(func.count()).select_from(Invoice).where(Invoice.supplier_id != supplier_id,
                                                                                   Invoice.payment_status == "UNPAID")).scalar()
    run_day = max(due, date(2026, 11, 2))
    with sc.act("finance.controller", at(run_day, 10)) as s:
        run = payables.payment_run(s, run_day, supplier_codes=[code])
    paid = {p["invoice"] for p in run["paid"]}
    assert number in paid and all(p["integrationStatus"] == "POSTED" for p in run["paid"])
    with tenant_tx(loaded["tenant_id"]) as db:
        invoice = db.execute(select(Invoice).where(Invoice.number == number)).scalar_one()
        assert invoice.status == "PAID" and invoice.payment_status == "PAID"
        assert {db.get(Invoice, p.invoice_id).supplier_id for p in db.execute(select(Payment).where(Payment.run_ref == run["run"])).scalars()} == {supplier_id}
        assert db.execute(select(func.count()).select_from(Invoice).where(Invoice.supplier_id != supplier_id,
                                                                          Invoice.payment_status == "UNPAID")).scalar() == others_unpaid
        assert db.execute(select(ErpDocument).where(ErpDocument.doc_no == invoice.erp_doc_no, ErpDocument.doc_type == "RE")).scalars().first()
    with sc.act("ap.clerk", at(run_day, 18)) as s:
        recon = payables.reconcile(s, "1000")
    assert recon["differences"] == 0, recon


def test_spend_overview_shows_the_loaded_history(loaded):
    from app.pic.services import spend
    sc = loaded["sc"]
    with sc.act("category.head", at(date(2026, 11, 10), 10)) as s:
        overview = spend.overview(s)
        expected = s.execute(select(func.sum(SpendLine.amount_minor)).where(SpendLine.period.between("2025-11", "2026-10"))).scalar()
        hits = s.execute(select(MaverickHit.rule_code, func.count()).group_by(MaverickHit.rule_code)).all()
    assert overview["periods"] == ["2025-11", "2026-10"] and overview["totalMinor"] == expected > 400 * 10_000_000 * 100
    assert Decimal(overview["contractedPct"]) > 30 and Decimal(overview["addressablePct"]) > 95
    assert {code for code, _ in hits} >= {"PO_AFTER_INVOICE", "OFF_CONTRACT"}
    classification = loaded["summary"]["classification"]
    assert classification["auto"] + classification["review"] > 500


def test_delta_extract_updates_masters_and_refuses_bank_changes(loaded, tmp_path):
    delta = tmp_path / "KAC-DELTA"
    shutil.copytree(DATA, delta)
    manifest = json.loads((delta / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest["extractId"], manifest["extractType"] = "KAC-S4H-20261108-DELTA", "DELTA"
    _edit_csv(delta / "LFA1.csv", "0000100002", "SPERR", "X")                 # vendor blocked in SAP since the initial load
    _edit_csv(delta / "LFBK.csv", "0000100003", "BANKN", "99990000111122")    # bank account changed in SAP
    for name in ("LFA1.csv", "LFBK.csv"):
        manifest["files"][name]["sha256"] = hashlib.sha256((delta / name).read_bytes()).hexdigest()
    (delta / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = erp_load.load("KAC", delta, when=at(date(2026, 11, 8), 7))
    assert _keys(result, "vendorBanks", "SENSITIVE_CHANGE") == ["100003"]
    with tenant_tx(loaded["tenant_id"]) as db:
        vendor = db.execute(select(Supplier).where(Supplier.code == "100002")).scalar_one()
        assert vendor.status == "BLOCKED" and vendor.screening["erpBlock"] == "SPERR"
        event = db.execute(select(AuditEvent).where(AuditEvent.object_id == vendor.id, AuditEvent.action == "ERP_DELTA")).scalar_one()
        assert event.actor == "integration:SAP_S4" and event.after == {"status": "BLOCKED"}
        unchanged = db.execute(select(SupplierBankAccount).join(Supplier, Supplier.id == SupplierBankAccount.supplier_id)
                               .where(Supplier.code == "100003")).scalar_one()
        assert crypto.decrypt(loaded["tenant_id"], "bank", unchanged.account_enc) != "99990000111122"
    assert all(v.get("loaded", 0) == 0 for v in result["objects"].values())
