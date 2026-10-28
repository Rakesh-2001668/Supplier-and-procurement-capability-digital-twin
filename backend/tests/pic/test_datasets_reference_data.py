"""D11 reference data (every tenant): CBIC HSN/SAC GST master as rule set HSN-GST and the invoice-match GST check, plant
holiday calendars from the state gazette lists, UNSPSC mapping as rule set TAXONOMY-UNSPSC, FBIL reference FX rates.

Negative checks (invoice matching against the master) run in transactions that roll back.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import AuditEvent, FxRate, Invoice, InvoiceException, Plant, PoLine, PurchaseOrder, RuleSet, Tenant
from app.pic.platform import clock
from app.pic.platform.errors import Problem
from app.pic.seed.axion import Scenario, at
from app.pic.seed.datasets import reference_data as pack_module
from tests.pic.conftest import PASSWORD


class _Rollback(Exception):
    pass


def _tenant_id(code: str):
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == code)).scalar_one()


@pytest.fixture(scope="module")
def pack(database):
    from app.pic.seed import datasets
    results = datasets.apply_pack("reference_data", PASSWORD)
    axn = next(r for r in results if r["tenant"] == "AXN")
    assert axn["status"] == "LOADED", results
    yield axn["summary"]
    clock.set_pinned(None)


@pytest.fixture(scope="module")
def sc(pack):
    return Scenario(_tenant_id("AXN"), "AXN")


def test_reference_files_carry_source_and_as_of_date():
    for name in ("hsn_gst_rates.csv", "holidays_2026_2027.csv", "unspsc_category_map.csv", "fx_reference_rates.csv"):
        header, rows = pack_module.read_reference(name)
        assert rows, name
        assert any("As of: 2026-10-28" in line for line in header), name
        assert any(word in " ".join(header) for word in ("CBIC", "G.O.", "UNGM", "FBIL")), name
    _, hsn = pack_module.read_reference("hsn_gst_rates.csv")
    assert len(hsn) >= 300 and {r["gst_rate"] for r in hsn} <= {"0", "5", "12", "18", "40"}
    assert {r["type"] for r in hsn} == {"HSN", "SAC"}
    assert all(p.isdigit() for r in hsn for p in r["prefixes"].split())


def test_hsn_master_rule_set_and_usage_check(pack, sc):
    counts = pack["counts"]
    assert counts["hsnEntries"] >= 300 and counts["hsnCodesInUse"] >= 3
    assert counts["hsnMismatched"] == 0, pack["notes"]  # the signature case uses 87089900, 73181500, 998717 at 18%
    with tenant_tx(sc.tenant_id) as s:
        rule = s.execute(select(RuleSet).where(RuleSet.key == "HSN-GST")).scalar_one()
        assert rule.version == pack_module.HSN_VERSION and rule.effective_from == date(2025, 9, 22)
        assert "9/2025-CT(Rate)" in rule.body["notifications"]
        assert s.execute(select(AuditEvent).where(AuditEvent.object_id == rule.id, AuditEvent.action == "VERSION_CREATED")).scalar_one()


def test_gst_lookup_and_check(sc):
    from app.pic.services import gst
    with sc.act("buyer", at(date(2027, 3, 31), 9)) as s:
        assert gst.lookup(s, "87089900")["rates"] == [Decimal(18)]           # auto parts: Sch II (18%) since 22.09.2025
        assert gst.lookup(s, "73181500")["rates"] == [Decimal(18)]           # fasteners
        assert gst.lookup(s, "90189011")["rates"] == [Decimal(5)]            # medical instruments: Sch I (5%)
        assert gst.lookup(s, "4015 19 00")["rates"] == [Decimal(5), Decimal(18)]  # surgical (5%) vs other gloves (18%)
        assert set(gst.lookup(s, "996791")["rates"]) == {Decimal(5), Decimal(18)}  # GTA: 5% without ITC or 18% with ITC
        assert gst.lookup(s, "998717")["matchedDigits"] == 6
        assert gst.check(s, "87089900", "18") is None
        finding = gst.check(s, "87089900", "28")                              # the pre-September-2025 auto-parts rate
        assert finding["allowedRates"] == ["18"] and finding["ruleSetVersion"].startswith("HSN-GST@")
        assert gst.check(s, "90189011", Decimal(12)) is not None              # medical devices moved from 12% to 5%
        assert gst.check(s, "99999999", "12") is None                         # unknown code: not judged
        assert gst.check(s, None, "12") is None
        assert gst.check(s, "84861000", "28") is None                         # only a chapter-level entry (84): not judged
        assert gst.check(s, "87089900", "28", on=date(2025, 9, 1)) is None    # before the schedule was in force


def _capture(sc, rate: str, invoice_no: str, set_po_rate: str | None = None) -> list[dict]:
    from app.pic.services import payables
    out = []
    try:
        with sc.act("ap.clerk", at(date(2027, 8, 16), 11)) as s:
            po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == "PO-77416")).scalar_one()
            line = s.execute(select(PoLine).where(PoLine.po_id == po.id, PoLine.line_no == 10)).scalar_one()
            if set_po_rate is not None:
                line.gst_rate = Decimal(set_po_rate)  # the PO line carries the same wrong rate (both documents agree)
                s.flush()
            invoice = payables.capture(s, supplier="KD002", supplier_invoice_no=invoice_no, invoice_date=date(2027, 8, 16), channel="PORTAL",
                                       lines=[{"po": "PO-77416", "po_line": 10, "qty": "37", "unit_price": "12.50", "gst_rate": rate,
                                               "hsn": "73181500"}])
            out = [{"type": e.type, "delta": e.delta, "detail": e.detail} for e in s.execute(
                select(InvoiceException).where(InvoiceException.invoice_id == invoice.id, InvoiceException.status == "OPEN")).scalars()]
            out.append({"status": s.get(Invoice, invoice.id).status})
            raise _Rollback
    except _Rollback:
        pass
    finally:
        clock.set_pinned(None)
    return out


def test_invoice_match_checks_the_scheduled_gst_rate(sc):
    clean = _capture(sc, "18", "KD/GST-CHECK-OK")
    assert clean[-1]["status"] in ("MATCHED", "APPROVED", "POSTED"), clean
    assert not [e for e in clean[:-1] if e["type"] == "TAX"]
    wrong = _capture(sc, "12", "KD/GST-CHECK-12", set_po_rate="12")
    tax = [e for e in wrong[:-1] if e["type"] == "TAX"]
    assert len(tax) == 1 and tax[0]["delta"]["allowedRates"] == ["18"] and tax[0]["delta"]["gstRate"] == "12", wrong
    assert "73181500" in tax[0]["detail"] and wrong[-1]["status"] == "EXCEPTION"
    with tenant_tx(sc.tenant_id) as s:  # nothing persisted
        assert not s.execute(select(Invoice.id).where(Invoice.supplier_invoice_no.like("KD/GST-CHECK-%"))).first()


def test_plant_calendars_from_tamil_nadu_gazette(pack, sc):
    with tenant_tx(sc.tenant_id) as s:
        for plant in s.execute(select(Plant).where(Plant.code.in_(("P100", "P200")))).scalars():
            days = set(plant.holidays)
            assert {date(2026, 10, 20), date(2026, 11, 8), date(2027, 1, 15)} <= days    # the signature-case dates are kept
            assert {date(2026, 1, 15), date(2026, 10, 19), date(2027, 1, 16), date(2027, 10, 28), date(2027, 12, 25)} <= days
            assert date(2026, 4, 1) not in days and date(2027, 4, 1) not in days        # bank closing day is not a factory holiday
            assert len(days) == 46
        events = s.execute(select(AuditEvent).where(AuditEvent.object_type == "PLANT", AuditEvent.action == "CALENDAR_UPDATED")).scalars().all()
        assert len(events) == 4 and all("G.O.(Ms.)" in e.reason for e in events)
    assert pack["counts"]["holidaysAdded"] == 86 and pack["counts"]["calendarsMissing"] == 0


def test_calendar_service_rules(sc):
    from app.pic.services import admin
    with sc.act("buyer", at(date(2027, 3, 31), 9)) as s:
        with pytest.raises(Problem) as exc:
            admin.add_plant_holidays(s, "P100", [date(2027, 12, 31)], "test list")
        assert exc.value.status == 403
    try:
        with sc.act("admin", at(date(2027, 3, 31), 9)) as s:
            with pytest.raises(Problem):
                admin.add_plant_holidays(s, "P100", [date(2027, 12, 31)], "")
            assert admin.add_plant_holidays(s, "P100", [date(2027, 1, 15)], "already there") == []
            raise _Rollback
    except _Rollback:
        pass


def test_unspsc_mapping(pack, sc):
    with tenant_tx(sc.tenant_id) as s:
        rule = s.execute(select(RuleSet).where(RuleSet.key == "TAXONOMY-UNSPSC")).scalar_one()
        nodes = rule.body["nodes"]
        assert nodes["ALU-DIECAST"][0]["family"] == "31100000" and nodes["ALU-DIECAST"][0]["familyTitle"] == "Castings and casting assemblies"
        assert nodes["FASTENERS"][0]["family"] == "31160000"
        assert nodes["LOGISTICS"][0]["class"] == "78101800"
        assert nodes["IC-TRANSFER"] == []
        assert rule.body["licensedCodeSet"] is False
    assert pack["counts"]["taxonomyUnmapped"] == 0, pack["notes"]


def test_fx_reference_rates(pack, sc):
    with tenant_tx(sc.tenant_id) as s:
        rates = {(r.from_ccy, r.to_ccy): r for r in s.execute(select(FxRate).where(FxRate.valid_from == date(2026, 10, 28))).scalars()}
        assert rates[("USD", "INR")].rate == Decimal("95.22780000") and rates[("USD", "INR")].source.startswith("FBIL")
        assert rates[("JPY", "INR")].rate == Decimal("0.60310000")  # FBIL quotes INR per 100 JPY
        assert len(rates) == 4
    from app.pic.services import admin
    with sc.act("category.head", at(date(2027, 3, 31), 9)) as s:
        assert admin.convert(s, 100_00, "USD", "INR")[0] == 9522_78


def test_idempotent(pack):
    from app.pic.seed import datasets
    again = datasets.apply_pack("reference_data", PASSWORD)
    assert {r["status"] for r in again} == {"ALREADY_LOADED"}
