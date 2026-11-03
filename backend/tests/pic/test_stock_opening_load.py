"""The opening-stock loader (tools/stock_opening_load.py), the production path for a tenant's opening position: validation of the file (every error names
its line, nothing is written when any line is wrong), dry run, posting through the ledger primitive as movement 561 at the standard price, the batch master,
idempotency per balance, balances that already hold other postings, and the reconciliation to the ERP stock list.

Own tenant (SOL1) so the demo tenants are not touched."""
import csv
import hashlib
import os
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.pic.db import tenant_tx
from app.pic.models import AuditEvent, Material, Stock, StockBatch, StockMovement, StorageLocation
from app.pic.platform import clock
from app.pic.seed.axion import at
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.services import stock_ledger
from app.pic.tools import stock_opening_load as loader

from .conftest import PASSWORD

CODE = os.environ.get("SOL_TEST_TENANT", "SOL1")
DOMAIN = f"{CODE.lower()}.example"
GSTIN = "29AAKCD4821M1Z7"
P1, P2 = "P100", "P200"
HEADER = ["material", "plant", "storage_location", "stock_type", "batch", "qty", "uom", "expiry", "valuation"]
USERS = [("admin", "Admin", ["TENANT_ADMIN"], {})]


@pytest.fixture(scope="module")
def env(database):
    sc = kit.setup_tenant(CODE, "Opening Stock Test Pvt Ltd", "MANUFACTURING", company=("1000", "Opening Stock Test Pvt Ltd", GSTIN),
                          plants=[(P1, "Plant one", "29"), (P2, "Plant two", "29")], cost_objects=[("COST_CENTER", "6100", "Test cost centre")],
                          holidays=[], domain=DOMAIN, role_user={})
    kit.create_users(sc, USERS, PASSWORD)
    with tenant_tx(sc.tenant_id) as s:
        s.add(StorageLocation(tenant_id=sc.tenant_id, plant=P1, code="0002", name="Second location"))
        s.add(StorageLocation(tenant_id=sc.tenant_id, plant=P1, code="0009", name="Closed location", active=False))
        for number, uom, price, extra in (("OL-A", "EA", 10_000, {}), ("OL-B", "KG", 2_500, {"attributes": {"batchManaged": True, "expiryManaged": True}}),
                                          ("OL-C", "EA", 500, {"type": "NON_STOCK"}), ("OL-NP", "EA", None, {}), ("OL-D", "L", 100_000, {"attributes": {"plants": [P2]}}),
                                          ("OL-E", "EA", 1_000, {})):
            values = dict(description=f"Opening test {number}", type="STOCK", material_group="GENERAL", category="GENERAL", base_uom=uom, mrp_type="PD",
                          lot_size_policy="EXACT", safety_stock=Decimal(0), planned_delivery_days=3, gr_processing_days=0, standard_price_minor=price,
                          status="ACTIVE", hsn_code="8708", gst_rate=Decimal(18))
            values.update(extra)
            s.add(Material(tenant_id=sc.tenant_id, number=number, **values))
    yield sc
    clock.set_pinned(None)


def write(path, rows, header=HEADER):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(c, "") if isinstance(row, dict) else row[i] for i, c in enumerate(header)])
    return path


def line(material, qty, **kw):
    base = {"material": material, "plant": P1, "storage_location": "0001", "stock_type": "UNRESTRICTED", "batch": "", "qty": qty, "uom": "EA", "expiry": "", "valuation": ""}
    base.update(kw)
    return base


def counts(env):
    with tenant_tx(env.tenant_id) as s:
        return {"stock": s.execute(select(func.count()).select_from(Stock)).scalar_one(), "movements": s.execute(select(func.count()).select_from(StockMovement)).scalar_one(),
                "batches": s.execute(select(func.count()).select_from(StockBatch)).scalar_one(), "audit": s.execute(select(func.count()).select_from(AuditEvent)).scalar_one()}


def refused(env, path, **kw):
    with pytest.raises(loader.LoadRefused) as caught:
        loader.load(CODE, path, **kw)
    return caught.value.summary


def codes(summary):
    return sorted((e["line"], e["code"]) for e in summary["errors"])


# ================================================================ validation
def test_a_file_with_wrong_lines_is_refused_whole_and_every_error_names_its_line(env, tmp_path):
    before = counts(env)
    rows = [
        line("OL-A", "10", valuation="1000.00"),                                          # line 2: fine
        line("NOPE", "1"),                                                                # 3 unknown material
        line("OL-C", "1"),                                                                # 4 not a stock material
        line("OL-A", "1", plant="P999"),                                                  # 5 unknown plant
        line("OL-A", "1", storage_location="0777"),                                       # 6 unknown storage location
        line("OL-A", "1", storage_location="0009"),                                       # 7 deactivated location
        line("OL-A", "-3"),                                                               # 8 negative
        line("OL-A", "1.2345"),                                                           # 9 more than three decimals
        line("OL-A", "abc"),                                                              # 10 not a number
        line("OL-A", "1", stock_type="FROZEN"),                                           # 11 stock type
        line("OL-A", "1", uom="KG"),                                                      # 12 unit differs from the base unit
        line("OL-B", "1", uom="KG"),                                                      # 13 batch managed without a batch
        line("OL-B", "1", uom="KG", batch="B1"),                                          # 14 expiry managed without an expiry
        line("OL-A", "1", expiry="2027-01-01"),                                           # 15 expiry without batch
        line("OL-B", "1", uom="KG", batch="B2", expiry="31.12.2027"),                     # 16 not an ISO date
        line("OL-A", "10", valuation="1000.00"),                                          # 17 the same balance as line 2
        line("OL-D", "1", uom="L"),                                                       # 18 material is only maintained at P200
        line("OL-A", "1", valuation="-5"),                                                # 19 bad valuation
        line("OL-A", "1", uom=""),                                                        # 20 no unit
    ]
    summary = refused(env, write(tmp_path / "bad.csv", rows))
    assert summary["status"] == "REFUSED" and summary["rows"] == 19
    assert codes(summary) == sorted([(3, "UNKNOWN_MATERIAL"), (4, "NOT_A_STOCK_MATERIAL"), (5, "UNKNOWN_PLANT"), (6, "UNKNOWN_LOCATION"), (7, "LOCATION_INACTIVE"),
                                     (8, "NEGATIVE_QTY"), (9, "TOO_MANY_DECIMALS"), (10, "BAD_NUMBER"), (11, "BAD_STOCK_TYPE"), (12, "UOM_MISMATCH"), (13, "BATCH_REQUIRED"),
                                     (14, "EXPIRY_REQUIRED"), (15, "EXPIRY_WITHOUT_BATCH"), (16, "BAD_DATE"), (17, "DUPLICATE_KEY"), (18, "MATERIAL_NOT_AT_PLANT"),
                                     (19, "BAD_VALUATION"), (20, "MISSING_VALUE")])
    assert all(e["message"] for e in summary["errors"])
    assert counts(env) == before                                                           # not one balance, movement, batch or audit event was written


def test_file_level_problems_are_refused_before_any_line_is_read(env, tmp_path):
    missing = write(tmp_path / "no_qty.csv", [], header=["material", "plant", "storage_location", "stock_type", "uom"])
    assert [e["code"] for e in refused(env, missing)["errors"]] == ["MISSING_COLUMN"]
    assert [e["code"] for e in refused(env, write(tmp_path / "empty.csv", []))["errors"]] == ["EMPTY_FILE"]
    binary = tmp_path / "binary.csv"
    binary.write_bytes(b"\xff\xfe\x00\x01")
    assert [e["code"] for e in refused(env, binary)["errors"]] == ["NOT_UTF8"]
    with pytest.raises(loader.LoadRefused) as caught:
        loader.load("NOSUCH", write(tmp_path / "x.csv", [line("OL-A", "1")]))
    assert caught.value.summary["errors"][0]["code"] == "UNKNOWN_TENANT"


def test_an_expiry_that_contradicts_the_batch_master_or_the_file_is_refused(env, tmp_path):
    rows = [line("OL-B", "1", uom="KG", batch="X1", expiry="2027-06-30"), line("OL-B", "1", uom="KG", plant=P2, batch="X1", expiry="2027-07-31")]
    summary = refused(env, write(tmp_path / "conflict.csv", rows))
    assert codes(summary) == [(3, "BATCH_EXPIRY_CONFLICT")]


# ================================================================ dry run, load, idempotency
GOOD = [
    line("OL-A", "120", valuation="12000.00"),                                             # 120 x INR 100
    line("OL-A", "5", storage_location="0002", valuation="500.00"),
    line("OL-B", "40.5", uom="KG", batch="L2610A", expiry="2027-03-31", valuation="1012.50"),
    line("OL-B", "10", uom="KG", batch="L2611B", expiry="2027-06-30", plant=P2, stock_type="QUALITY", valuation="250.00"),
    line("OL-B", "3", uom="KG", batch="L2610A", expiry="2027-03-31", stock_type="BLOCKED", valuation="75.00"),
    line("OL-A", "0", plant=P2),                                                           # a stock-out: nothing to post, listed in the report
    line("OL-D", "2", uom="L", plant=P2, stock_type="CONSIGNMENT", valuation="2000.00"),
]


def test_a_dry_run_validates_and_reconciles_but_writes_nothing(env, tmp_path):
    before = counts(env)
    summary = loader.load(CODE, write(tmp_path / "ok.csv", GOOD), dry_run=True)
    assert summary["status"] == "DRY_RUN" and summary["dryRun"] and summary["toPost"] == 6 and summary["zeroQuantity"] == 1 and summary["alreadyLoaded"] == 0
    assert summary["reconciliation"]["status"] == "RECONCILED" and summary["reconciliation"]["fileMinor"] == summary["reconciliation"]["picMinor"] == 1_583_750
    assert counts(env) == before


def test_the_load_posts_561_at_the_standard_price_records_batches_and_audits(env, tmp_path):
    path = write(tmp_path / "ok.csv", GOOD)
    clock.set_pinned(at(date(2026, 11, 9), 8))
    summary = loader.load(CODE, path)
    clock.set_pinned(None)
    assert summary["status"] == "LOADED" and summary["posted"] == 6 and summary["zeroQuantity"] == 1 and summary["batchesRecorded"] == 2
    assert summary["stockOuts"] == [{"material": "OL-A", "plant": P2}]
    with tenant_tx(env.tenant_id) as s:
        ids = {m.number: m.id for m in s.execute(select(Material)).scalars()}
        a = stock_ledger.on_hand(s, ids["OL-A"], P1, "0001")
        assert a == 120 and stock_ledger.on_hand(s, ids["OL-A"], P1, "0002") == 5 and stock_ledger.on_hand(s, ids["OL-A"], P2) == 0
        assert stock_ledger.on_hand(s, ids["OL-B"], P1, "0001", "UNRESTRICTED", "L2610A") == Decimal("40.5")
        assert stock_ledger.on_hand(s, ids["OL-B"], P2, "0001", "QUALITY", "L2611B") == 10
        assert stock_ledger.on_hand(s, ids["OL-B"], P1, "0001", "BLOCKED", "L2610A") == 3
        assert stock_ledger.on_hand(s, ids["OL-D"], P2, "0001", "CONSIGNMENT") == 2
        movements = s.execute(select(StockMovement)).scalars().all()
        assert len(movements) == 6 and all(m.movement_type == "561" and m.reference_type == "OPENING_BALANCE" and m.reason_code == "OPENING" and m.posting_ref == f"OPEN-{CODE}"
                                           for m in movements)
        values = {(m.material_id, m.stock_type, m.batch, m.plant, m.storage_location): m.value_minor for m in movements}
        assert values[(ids["OL-A"], "UNRESTRICTED", "", P1, "0001")] == 1_200_000 and values[(ids["OL-B"], "UNRESTRICTED", "L2610A", P1, "0001")] == 101_250
        # no balance exists for the stock-out line
        assert s.execute(select(func.count()).select_from(Stock).where(Stock.material_id == ids["OL-A"], Stock.plant == P2)).scalar_one() == 0
        # the batch master carries the expiry (one row per material and batch) and the ledger reads it
        assert {(b.batch, b.expiry_date.isoformat(), b.source) for b in s.execute(select(StockBatch)).scalars()} == {
            ("L2610A", "2027-03-31", "OPENING_BALANCE"), ("L2611B", "2027-06-30", "OPENING_BALANCE")}
        assert stock_ledger.batch_expiry(s, ids["OL-B"]) == {"L2610A": date(2027, 3, 31), "L2611B": date(2027, 6, 30)}
        assert stock_ledger.expiry_for_pairs(s, {(ids["OL-B"], "L2610A"), (ids["OL-A"], "")}) == {(ids["OL-B"], "L2610A"): date(2027, 3, 31)}
        audit = s.execute(select(AuditEvent).where(AuditEvent.action == "INITIAL_LOAD", AuditEvent.object_type == "MIGRATION")).scalars().all()
        assert len(audit) == 1 and audit[0].after["balances"] == 6 and audit[0].after["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert audit[0].actor == loader.ACTOR
    clash = refused(env, write(tmp_path / "clash.csv", [line("OL-B", "1", uom="KG", batch="L2610A", expiry="2027-04-30", plant=P2)]))
    assert codes(clash) == [(2, "BATCH_EXPIRY_CONFLICT")] and "already has expiry 2027-03-31" in clash["errors"][0]["message"]


def test_loading_the_same_file_again_changes_nothing_and_an_extended_file_adds_only_the_new_balance(env, tmp_path):
    before = counts(env)
    again = loader.load(CODE, write(tmp_path / "ok.csv", GOOD))
    assert again["status"] == "NOTHING_TO_POST" and again["posted"] == 0 and again["alreadyLoaded"] == 6 and again["zeroQuantity"] == 1
    assert counts(env) == before
    extended = loader.load(CODE, write(tmp_path / "more.csv", GOOD + [line("OL-E", "7", valuation="70.00")]))
    assert extended["posted"] == 1 and extended["alreadyLoaded"] == 6
    after = counts(env)
    assert after["movements"] == before["movements"] + 1 and after["stock"] == before["stock"] + 1


def test_a_balance_that_already_holds_other_postings_is_skipped_with_a_warning(env, tmp_path):
    with env.act("admin", at(date(2026, 11, 10), 9)) as s:
        material = s.execute(select(Material).where(Material.number == "OL-E")).scalar_one()
        stock_ledger.post_movement(s, material_id=material.id, plant=P2, sloc="0001", stock_type="UNRESTRICTED", qty=Decimal(4), movement="101", ref_type="GOODS_RECEIPT",
                                   ref_id=material.id, ref="GR-TEST")
    clock.set_pinned(None)
    summary = loader.load(CODE, write(tmp_path / "used.csv", [line("OL-E", "50", plant=P2)]))
    assert summary["skippedInUse"] == 1 and summary["posted"] == 0 and any("already holds other postings" in w for w in summary["warnings"])
    with tenant_tx(env.tenant_id) as s:
        material = s.execute(select(Material).where(Material.number == "OL-E")).scalar_one()
        assert stock_ledger.on_hand(s, material.id, P2) == 4


# ================================================================ reconciliation, strict mode, command line
def test_reconciliation_lists_the_lines_whose_value_differs_and_strict_refuses_them(env, tmp_path):
    rows = [line("OL-E", "10", valuation="100.00"), line("OL-A", "10", valuation="1000.00"), line("OL-A", "20", storage_location="0002", valuation="1990.00")]
    summary = loader.load(CODE, write(tmp_path / "recon.csv", rows), dry_run=True)
    r = summary["reconciliation"]
    assert r["status"] == "DIFFERENCES" and r["differingCount"] == 1 and r["fileMinor"] == 10_000 + 100_000 + 199_000 and r["picMinor"] == 10_000 + 100_000 + 200_000
    assert r["differenceMinor"] == 1_000 and r["byPlant"][P1]["lines"] == 3 and r["differingLines"][0]["line"] == 4 and r["differingLines"][0]["differenceMinor"] == 1_000
    assert refused(env, tmp_path / "recon.csv", strict=True)["errors"][0]["code"] == "NOT_RECONCILED"
    exact = loader.load(CODE, write(tmp_path / "exact.csv", [line("OL-E", "10", valuation="100.00")]), dry_run=True)
    assert exact["reconciliation"]["status"] == "RECONCILED" and exact["reconciliation"]["differenceMinor"] == 0


def test_a_material_without_a_standard_price_loads_with_a_warning_and_no_value(env, tmp_path):
    summary = loader.load(CODE, write(tmp_path / "np.csv", [line("OL-NP", "9")]))
    assert summary["posted"] == 1 and any("no standard price" in w for w in summary["warnings"])
    with tenant_tx(env.tenant_id) as s:
        movement = s.execute(select(StockMovement).join(Material, Material.id == StockMovement.material_id).where(Material.number == "OL-NP")).scalar_one()
        assert movement.value_minor is None and movement.qty == 9


def test_the_command_line_exit_codes_and_report(env, tmp_path, capsys):
    good = write(tmp_path / "cli_ok.csv", [line("OL-A", "1", plant=P2, valuation="100.00")])
    assert loader.main(["--tenant", CODE, "--file", str(good), "--dry-run", "--report", str(tmp_path / "r.json")]) == 0
    out = capsys.readouterr().out
    assert "DRY_RUN" in out and "reconciliation" in out and "RECONCILED" in out and (tmp_path / "r.json").exists()
    bad = write(tmp_path / "cli_bad.csv", [line("NOPE", "1")])
    assert loader.main(["--tenant", CODE, "--file", str(bad)]) == 2
    out = capsys.readouterr().out
    assert "REFUSED" in out and "line 2" in out and "UNKNOWN_MATERIAL" in out
    assert loader.main(["--tenant", CODE, "--file", str(good)]) == 0 and "LOADED" in capsys.readouterr().out
