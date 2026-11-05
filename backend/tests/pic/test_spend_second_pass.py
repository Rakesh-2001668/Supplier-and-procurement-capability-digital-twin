"""Spend cube second pass (4 November 2026): adversarial probes of M01 (docs/PIC_Spend_Cube_Analysis.md), one test per defect (S1..) or gap.

Own tenant SP2. Documents (PO, invoice, credit / debit note) are written as rows and fed through the same functions the event consumers call
(``spend_feed``), the event path itself is proved by emitting the events and relaying them; everything else goes through the HTTP API.
Assertions are about properties of this tenant's data, never about global counts.
"""
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.pic.db import tenant_tx
from app.pic.models import (
    AppUser, CreditNote, DebitNote, FxRate, Invoice, InvoiceLine, Material, MaverickHit, PoLine, PurchaseOrder, SpendLine, Supplier,
    SupplierCategoryStatus, TaxonomyNode,
)
from app.pic.platform import clock, outbox
from app.pic.platform.errors import Problem
from app.pic.seed.axion import at
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.services import spend, spend_analytics, spend_cube, spend_feed, spend_forecast, spend_quality, spend_scope

from .conftest import PASSWORD

CODE = os.environ.get("SP2_TEST_TENANT", "SP2")
DOMAIN = f"{CODE.lower()}.example"
GSTIN = "29AAKCD4821M1Z7"
TODAY = date(2026, 11, 4)
J: dict = {}
USERS = [
    ("admin", "Admin Anil", ["TENANT_ADMIN"], {}),
    ("cm", "Chandra Category", ["CATEGORY_MANAGER"], {}),
    ("cm2", "Chitra Category", ["CATEGORY_MANAGER"], {}),
    ("ph", "Pranav Procurement", ["PROCUREMENT_HEAD"], {}),
    ("ph2", "Prem Procurement", ["PROCUREMENT_HEAD"], {}),
    ("cpo", "Cara CPO", ["CPO"], {}),
    ("steward", "Sita Steward", ["MDM_STEWARD"], {}),
    ("steward2", "Sam Steward", ["MDM_STEWARD"], {}),
    ("fin", "Farid Finance", ["FINANCE_CONTROLLER"], {}),
    ("buyer", "Bala Buyer", ["BUYER"], {}),
    ("plant2", "Pia Plant-Two", ["CATEGORY_MANAGER"], {"plants": ["P2"]}),
    ("alucat", "Alu Only", ["CATEGORY_MANAGER"], {"categories": ["ALU-DIECAST"]}),
    ("cc", "Cost-centre Only", ["CATEGORY_MANAGER"], {"cost_centres": ["CC-77"]}),
    ("group", "Supplier-group Only", ["CATEGORY_MANAGER"], {"supplier_groups": ["S-PARENT"]}),
]
ROLE_USER = {"CATEGORY_MANAGER": "cm", "PROCUREMENT_HEAD": "ph", "CPO": "cpo", "MDM_STEWARD": "steward", "FINANCE_CONTROLLER": "fin"}


def _email(local: str) -> str:
    return f"{local}@{DOMAIN}"


def _h(login, local: str) -> dict:
    return login(_email(local), CODE)


def _problem(r, status: int, code: str | None = None) -> dict:
    assert r.status_code == status, r.text
    body = r.json()
    if code:
        assert body["code"] == code, body
    return body


@pytest.fixture(scope="module")
def env(database):
    clock.set_pinned(at(TODAY, 10))
    sc = kit.setup_tenant(CODE, "Spend Second Pass Industries Pvt Ltd", "MANUFACTURING", company=("1000", "Spend Second Pass Industries Pvt Ltd", GSTIN),
                          plants=[("P1", "Plant one", "29"), ("P2", "Plant two", "29")],
                          cost_objects=[("COST_CENTER", "CC-77", "Cost centre 77"), ("COST_CENTER", "CC-10", "Cost centre 10")], holidays=[],
                          domain=DOMAIN, role_user=ROLE_USER)
    kit.create_users(sc, USERS, PASSWORD)
    kit.rule_version(sc, "MFA", "2026.1-SP2", date(2026, 4, 1), {"enforce": False}, "Spend second pass tenant: no MFA challenge for the API tests")
    J["sc"], J["tid"] = sc, sc.tenant_id
    with tenant_tx(sc.tenant_id) as s:
        spend.ensure_taxonomy(s, sc.tenant_id)
        J["buyer_id"] = s.execute(select(AppUser.id).where(AppUser.email == _email("buyer"))).scalar_one()
        J["cm_id"] = s.execute(select(AppUser.id).where(AppUser.email == _email("cm"))).scalar_one()
        suppliers = {}
        for code, name, kw in (("S-ALPHA", "Alpha Alloys Pvt Ltd", {}), ("S-BETA", "Beta Bearings Pvt Ltd", {}), ("S-GAMMA", "Gamma Gaskets Pvt Ltd", {}),
                               ("S-IC", "Group Company Machining Ltd", {"segment": "INTERCOMPANY"}), ("S-PARENT", "Parent Industries Ltd", {}),
                               ("S-CHILD", "Parent Industries Foundry Ltd", {}), ("S-UNI", "Zażółć Gęślą Jaźń Spółka", {})):
            sup = Supplier(tenant_id=sc.tenant_id, code=code, legal_name=name, status="QUALIFIED", **kw)
            s.add(sup)
            suppliers[code] = sup
        s.flush()
        suppliers["S-CHILD"].parent_supplier_id = suppliers["S-PARENT"].id
        J["sup"] = {k: v.id for k, v in suppliers.items()}
        for number, category in (("SP2-M-ALU", "ALU-DIECAST"), ("SP2-M-FAS", "FASTENERS"), ("SP2-M-RUB", "RUBBER-SEALS")):
            s.add(Material(tenant_id=sc.tenant_id, number=number, description=f"{category} test material", type="STOCK", material_group=category, category=category,
                           base_uom="EA", mrp_type="PD", lot_size_policy="EXACT", safety_stock=Decimal(0), planned_delivery_days=3, gr_processing_days=0,
                           standard_price_minor=900_00, status="ACTIVE"))
        for code in ("S-ALPHA", "S-BETA"):
            for category in ("ALU-DIECAST", "FASTENERS"):
                s.add(SupplierCategoryStatus(tenant_id=sc.tenant_id, supplier_id=suppliers[code].id, category=category, status="QUALIFIED",
                                             qualified_on=date(2025, 4, 1)))
        for ccy, rate, day in (("USD", "83.00", date(2026, 3, 30)), ("USD", "84.00", date(2026, 4, 1)), ("USD", "85.00", date(2026, 10, 1))):
            s.add(FxRate(tenant_id=sc.tenant_id, from_ccy=ccy, to_ccy="INR", rate=Decimal(rate), valid_from=day, source="test"))
    return sc


_seq = iter(range(1, 100000))


def _doc(*, supplier="S-ALPHA", plant="P1", category="ALU-DIECAST", qty=10, price=1000_00, day=date(2026, 8, 10), currency="INR", po_created=None,
         received=None, invoiced_qty=None, invoiced_minor=None, released=True, po_status="RECEIVED", material=True, contract_line=None, free_text=False, deviation=False,
         cost_object=None, feed=True, tag=None):
    """A PO with one line and a posted invoice for it (rows), fed to the cube the way the invoice.posted consumer does. Returns the ids."""
    n = next(_seq)
    tag = tag or f"{n:05d}"
    with tenant_tx(J["tid"]) as s:
        sup = J["sup"][supplier]
        mat = s.execute(select(Material).where(Material.category == category)).scalars().first() if material else None
        po = PurchaseOrder(tenant_id=J["tid"], number=f"SP2-PO-{tag}", company_code="1000", purch_org="1000", plant=plant, supplier_id=sup, status=po_status,
                           purpose_code="PRODUCTION", currency=currency, total_minor=qty * price, payment_terms="N30", rule_set_version="test",
                           released_at=datetime.combine(day - timedelta(days=5), datetime.min.time(), tzinfo=timezone.utc) if released else None,
                           created_by=J["buyer_id"], created_at=po_created or datetime.combine(day - timedelta(days=10), datetime.min.time(), tzinfo=timezone.utc))
        s.add(po)
        s.flush()
        pl = PoLine(tenant_id=J["tid"], po_id=po.id, line_no=10, item_type="FREE_TEXT" if free_text else "MATERIAL", purchase_type="STOCK",
                    material_id=mat.id if mat else None, description=f"{category} part {tag}", material_group=category, qty=Decimal(qty), uom="EA",
                    unit_price_minor=price, net_minor=qty * price, gst_rate=Decimal(18), need_date=day, plant=plant, gr_required=True, price_source="MANUAL",
                    received_qty=Decimal(qty if received is None else received), invoiced_qty=Decimal(qty if invoiced_qty is None else invoiced_qty),
                    invoiced_minor=qty * price if invoiced_minor is None else invoiced_minor, contract_line_id=contract_line,
                    account_assignment_type="COST_CENTER" if cost_object else None, account_assignment_code=cost_object,
                    price_deviation=deviation, deviation_reason="test deviation" if deviation else None)
        s.add(pl)
        s.flush()
        inv = Invoice(tenant_id=J["tid"], number=f"SP2-INV-{tag}", supplier_invoice_no=f"SI-{tag}", fiscal_year="2026-27" if day >= date(2026, 4, 1) else "2025-26",
                      company_code="1000", supplier_id=sup, invoice_date=day, channel="PORTAL", net_minor=qty * price, tax_minor=0, gross_minor=qty * price,
                      currency=currency, status="POSTED", created_by=J["buyer_id"])
        s.add(inv)
        s.flush()
        il = InvoiceLine(tenant_id=J["tid"], invoice_id=inv.id, line_no=1, po_line_id=pl.id, description=pl.description, qty=Decimal(qty), unit_price_minor=price,
                         net_minor=qty * price, gst_rate=Decimal(18), tax_minor=0)
        s.add(il)
        s.flush()
        ids = {"po": po.id, "po_line": pl.id, "invoice": inv.id, "invoice_line": il.id, "number": inv.number, "po_number": po.number}
        if feed:
            spend_feed.feed_invoice(s, inv)
    return ids


def _note(ids, *, kind="credit", qty="4", day=date(2026, 8, 20), unit_credit=None, number=None, lines=None, gross=None):
    n = next(_seq)
    number = number or f"SP2-{kind[:2].upper()}N-{n:05d}"
    with tenant_tx(J["tid"]) as s:
        inv = s.get(Invoice, ids["invoice"])
        if kind == "credit":
            entry = {"invoice_line": 1, "qty": qty, **({"unitCreditMinor": unit_credit} if unit_credit is not None else {})}
            note = CreditNote(tenant_id=J["tid"], number=number, supplier_credit_note_no=number, supplier_id=inv.supplier_id, invoice_id=inv.id, note_date=day,
                              reason="test", net_minor=gross or 1, tax_minor=0, gross_minor=gross or 1, lines=lines or [entry])
        else:
            note = DebitNote(tenant_id=J["tid"], number=number, supplier_debit_note_no=number, supplier_id=inv.supplier_id, invoice_id=inv.id, note_date=day,
                             reason="test", status="POSTED", net_minor=gross or 1, tax_minor=0, gross_minor=gross or 1, lines=lines)
        s.add(note)
        s.flush()
        # the REAL payload of each event (the committed outbox rows are validated against the event schemas by the catalogue test)
        if kind == "credit":
            outbox.emit(s, "credit_note.received", "CREDIT_NOTE", note.id, note.number,
                        {"creditNoteId": str(note.id), "invoiceId": str(inv.id), "invoice": inv.number, "grossMinor": note.gross_minor, "noteDate": day.isoformat()})
        else:
            outbox.emit(s, "debit_note.posted", "DEBIT_NOTE", note.id, note.number,
                        {"invoice": inv.number, "erpDocument": f"ERP-{note.number}", "grossMinor": note.gross_minor})
    return number


def _lines(invoice_number: str, **filters):
    with tenant_tx(J["tid"]) as s:
        q = select(SpendLine).where(SpendLine.invoice_ref == invoice_number).order_by(SpendLine.document_type.collate("C"), SpendLine.document_ref.collate("C"))
        return [(l.document_type, l.document_ref, l.period, l.amount_minor, l.category, l.maverick_flags, l.addressable, l.price_variance_minor) for l in s.execute(q).scalars()]


def _relay() -> int:
    return outbox.relay_tenant(J["tid"])


def _cube(dims, **flt):
    with tenant_tx(J["tid"]) as s:
        return spend_cube.cube(s, dims, spend_cube.CubeFilter(**flt), limit=5000)


def _own_lines(tag: str) -> list:
    return [l for l in _all_lines() if l[0].startswith(tag)]


def _all_lines():
    with tenant_tx(J["tid"]) as s:
        return [(l.invoice_ref, l.document_type, l.period, l.amount_minor) for l in s.execute(select(SpendLine)).scalars()]


# ---------------------------------------------------------------- S1..S3 credit and debit notes
def test_spend2_s1_credit_note_after_posting_nets_the_spend_in_the_period_of_the_note(env):
    """S1: a credit note submitted after invoice.posted never reached the cube (the consumer only read credit notes that existed at posting)."""
    ids = _doc(day=date(2026, 3, 30), qty=10, price=1000_00, tag="S1")
    note = _note(ids, qty="4", day=date(2026, 4, 2))
    assert _relay() >= 1
    rows = _lines(ids["number"])
    assert [(r[0], r[2], r[3]) for r in rows] == [("CREDIT_NOTE", "2026-04", -4_000_00), ("INVOICE", "2026-03", 10_000_00)]
    assert rows[0][1] == note and sum(r[3] for r in rows) == 6_000_00
    # replaying the event (or the backfill) does not add a second credit line
    with tenant_tx(J["tid"]) as s:
        assert spend_feed.backfill_notes(s) == {"creditNoteLines": 0, "debitNoteLines": 0}
    # the fiscal-year boundary: the invoice is 31 March (FY 2025-26), the credit 2 April (FY 2026-27); neither year is restated
    cube = _cube(["fiscal_year"], suppliers=["S-ALPHA"], period_from="2026-03", period_to="2026-04")
    by_fy = {r["fiscal_year"]: r for r in cube["rows"]}
    assert by_fy["2025-26"]["invoicedMinor"] >= 10_000_00 and by_fy["2026-27"]["creditNoteMinor"] <= -4_000_00
    march = _cube(["period"], suppliers=["S-ALPHA"], period_from="2026-03", period_to="2026-03")["rows"][0]
    assert march["invoices"] >= 1
    april = {r["period"]: r for r in _cube(["period"], suppliers=["S-ALPHA"], period_from="2026-04", period_to="2026-04")["rows"]}["2026-04"]
    assert april["creditNoteMinor"] <= -4_000_00 and april["invoices"] == 0, "a credit note is not an invoice"


def test_spend2_s2_a_price_credit_reduces_the_value_not_the_quantity(env):
    """S2: the old consumer subtracted the credited QUANTITY of a value credit (qty x unit credit) from the line: a Rs 100 / unit price credit on 10
    units removed all 10 units (Rs 10,000) instead of Rs 1,000."""
    ids = _doc(day=date(2026, 8, 12), qty=10, price=1000_00, tag="S2")
    _note(ids, qty="10", unit_credit=100_00, day=date(2026, 8, 25))
    _relay()
    rows = _lines(ids["number"])
    assert sorted(r[3] for r in rows) == [-1_000_00, 10_000_00]
    assert not any(r[1] == "" and r[3] != 10_000_00 for r in rows), "the invoice line keeps its full quantity"


def test_spend2_s3_debit_notes_add_to_spend_and_a_charge_is_classified_from_its_text(env):
    ids = _doc(day=date(2026, 8, 12), qty=5, price=2000_00, tag="S3")
    _note(ids, kind="debit", day=date(2026, 8, 30), lines=[{"kind": "PRICE", "invoice_line": 1, "qty": "5", "unitDebitMinor": 100_00, "netMinor": 500_00},
                                                          {"kind": "CHARGE", "description": "Freight and transport charges", "netMinor": 250_00}], gross=750_00)
    _relay()
    rows = _lines(ids["number"])
    assert sorted((r[0], r[3]) for r in rows) == [("DEBIT_NOTE", 250_00), ("DEBIT_NOTE", 500_00), ("INVOICE", 10_000_00)]
    charge = next(r for r in rows if r[3] == 250_00)
    assert charge[4] == "LOGISTICS", "the additional charge is classified from its description, not left on the invoice's category"
    with tenant_tx(J["tid"]) as s:
        total = spend_cube.cube(s, ["period"], spend_cube.CubeFilter(period_from="2026-08", period_to="2026-08", suppliers=["S-ALPHA"]))
        assert total["totals"]["debitNoteMinor"] >= 750_00


def test_spend2_s3b_notes_before_the_invoice_is_fed_are_picked_up_when_it_is(env):
    ids = _doc(day=date(2026, 7, 3), qty=2, price=500_00, tag="S3B", feed=False)
    _note(ids, qty="1", day=date(2026, 7, 9))
    _relay()                       # the credit event arrives first: nothing to correct yet
    assert _lines(ids["number"]) == []
    with tenant_tx(J["tid"]) as s:
        spend_feed.feed_invoice(s, s.get(Invoice, ids["invoice"]))
    assert sorted(r[3] for r in _lines(ids["number"])) == [-500_00, 1_000_00]


# ---------------------------------------------------------------- S4 scope
def test_spend2_s4_a_plant_scoped_user_sees_totals_of_the_plant_only(client, login, env):
    """S4: no spend read applied the ABAC scope: a user restricted to plant P2 got the totals of every plant."""
    _doc(plant="P1", day=date(2026, 9, 5), qty=7, price=1000_00, tag="S4A")
    _doc(plant="P2", day=date(2026, 9, 6), qty=3, price=1000_00, category="FASTENERS", tag="S4B")
    _doc(plant="P1", day=date(2026, 9, 7), qty=1, price=10_00, currency="USD", tag="S4C")
    h = _h(login, "plant2")
    r = client.get("/v1/spend/analysis?dims=plant&period_from=2026-09&period_to=2026-09", headers=h).json()
    assert [x["plant"] for x in r["rows"]] == ["P2"] and r["totalMinor"] == r["rows"][0]["spendMinor"] and r["scope"] == {"plants": ["P2"]}
    assert "documentCurrencyTotals" not in r or "USD" not in r["documentCurrencyTotals"], "a P1 foreign line leaks through the currency totals"
    everyone = client.get("/v1/spend/analysis?dims=plant&period_from=2026-09&period_to=2026-09", headers=_h(login, "cm")).json()
    assert {x["plant"] for x in everyone["rows"]} >= {"P1", "P2"} and everyone["totalMinor"] > r["totalMinor"]
    # every other read agrees with the scope
    overview = client.get("/v1/spend/overview", headers=h).json()
    full = client.get("/v1/spend/overview", headers=_h(login, "cm")).json()
    assert overview["totalMinor"] < full["totalMinor"] and overview["scope"] == {"plants": ["P2"]}
    tree = client.get("/v1/spend/treemap", headers=h).json()
    assert sum(seg["valueMinor"] for seg in tree["segments"]) == overview["totalMinor"]
    sup = client.get("/v1/spend/suppliers", headers=h).json()
    assert sup["totalMinor"] <= max(overview["addressableMinor"], 1)
    lines = client.get("/v1/spend/lines?limit=500", headers=h).json()
    assert lines["lines"] and {l["plant"] for l in lines["lines"]} == {"P2"}
    export = client.get("/v1/spend/export?kind=lines&period_from=2026-09&period_to=2026-09", headers=h)
    assert export.status_code == 200 and len(export.text.splitlines()) > 1
    assert all(",P1," not in line for line in export.text.splitlines()[1:]), "the export carries only the lines inside the scope"


def test_spend2_s4b_category_cost_centre_and_supplier_group_scopes(client, login, env):
    _doc(category="ALU-DIECAST", day=date(2026, 9, 9), qty=2, price=1000_00, cost_object="CC-77", tag="S4D")
    _doc(category="FASTENERS", day=date(2026, 9, 9), qty=2, price=1000_00, cost_object="CC-10", tag="S4E", supplier="S-CHILD")
    flt = "period_from=2026-09&period_to=2026-09"
    alu = client.get(f"/v1/spend/analysis?dims=category&{flt}", headers=_h(login, "alucat")).json()
    assert {r["category"] for r in alu["rows"]} == {"ALU-DIECAST"}
    cc = client.get(f"/v1/spend/analysis?dims=cost_object&{flt}", headers=_h(login, "cc")).json()
    assert {r["cost_object"] for r in cc["rows"]} == {"CC-77"}
    grp = client.get(f"/v1/spend/analysis?dims=supplier&{flt}", headers=_h(login, "group")).json()
    assert {r["supplier"] for r in grp["rows"]} == {"S-CHILD"}, "the supplier-group scope includes the children of the parent"
    # an out-of-scope user has no way to name what they cannot see: filters narrow, they never widen
    wide = client.get(f"/v1/spend/analysis?dims=plant&plant=P1&{flt}", headers=_h(login, "plant2")).json()
    assert wide["rows"] == [] and wide["totalMinor"] == 0


def test_spend2_s4c_a_scoped_steward_queue_and_hits_are_scoped(client, login, env):
    with tenant_tx(J["tid"]) as s:
        keep = spend.gov(s)
    ids1 = _doc(plant="P1", category="UNKNOWNCAT", material=False, day=date(2026, 9, 10), qty=1, price=300_00, tag="S4F")
    ids2 = _doc(plant="P2", category="UNKNOWNCAT", material=False, day=date(2026, 9, 10), qty=1, price=300_00, tag="S4G")
    scoped = client.get("/v1/spend/classification-queue?status=OPEN&limit=500", headers=_h(login, "plant2")).json()
    full = client.get("/v1/spend/classification-queue?status=OPEN&limit=500", headers=_h(login, "cm")).json()
    assert {i["invoice_ref"] for i in scoped["items"]} <= {i["invoice_ref"] for i in full["items"]}
    assert ids2["number"] in {i["invoice_ref"] for i in scoped["items"]} and ids1["number"] not in {i["invoice_ref"] for i in scoped["items"]}
    assert keep is not None


# ---------------------------------------------------------------- S5 intercompany
def test_spend2_s5_intercompany_suppliers_are_not_addressable_spend(env):
    """S5: a platform invoice from an intercompany supplier was addressable (only the IC-TRANSFER category was excluded)."""
    ids = _doc(supplier="S-IC", day=date(2026, 8, 3), qty=4, price=1000_00, tag="S5")
    assert _lines(ids["number"])[0][6] is False
    cube = _cube(["addressable"], suppliers=["S-IC"])
    assert [r["addressable"] for r in cube["rows"]] == [False] and cube["totals"]["contractCoveragePct"] == "0"


# ---------------------------------------------------------------- S6 maverick rules
def test_spend2_s6_the_three_payment_control_rules_are_evaluated_for_new_invoices(env):
    """S6: NO_GOODS_RECEIPT, PO_NOT_APPROVED and OVER_INVOICED only existed in the legacy seed; the live consumer never raised them."""
    a = _doc(day=date(2026, 8, 3), qty=10, price=1000_00, received=0, tag="S6A")
    b = _doc(day=date(2026, 8, 3), qty=10, price=1000_00, released=False, po_status="IN_APPROVAL", tag="S6B")
    c = _doc(day=date(2026, 8, 3), qty=10, price=1000_00, invoiced_qty=13, invoiced_minor=13 * 1000_00, tag="S6C")
    clean = _doc(day=date(2026, 8, 3), qty=10, price=1000_00, tag="S6D")
    assert "NO_GOODS_RECEIPT" in _lines(a["number"])[0][5]
    assert "PO_NOT_APPROVED" in _lines(b["number"])[0][5]
    assert "OVER_INVOICED" in _lines(c["number"])[0][5]
    assert _lines(clean["number"])[0][5] == []
    with tenant_tx(J["tid"]) as s:
        hit = s.execute(select(MaverickHit).where(MaverickHit.invoice_ref == c["number"], MaverickHit.rule_code == "OVER_INVOICED")).scalar_one()
        assert hit.owner_role == "FINANCE_CONTROLLER" and hit.due_at is not None and hit.amount_group_minor == 10_000_00
        assert hit.savings_at_risk_minor == 3 * 1000_00, "the excess over the PO value (13 invoiced against 10 ordered) is what is at risk"


def test_spend2_s6b_po_after_invoice_uses_the_tenant_calendar_day(env):
    """S6b: the PO's UTC date was compared with the invoice date: a PO created at 01:00 IST on the invoice day + 1 is after the invoice, the UTC date says it is not."""
    inv_day = date(2026, 8, 3)
    late_ist = datetime(2026, 8, 4, 1, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))        # 3 Aug 19:30 UTC, 4 Aug IST
    early_ist = datetime(2026, 8, 3, 23, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    after = _doc(day=inv_day, po_created=late_ist, tag="S6E")
    same_day = _doc(day=inv_day, po_created=early_ist, tag="S6F")
    assert "PO_AFTER_INVOICE" in _lines(after["number"])[0][5]
    assert "PO_AFTER_INVOICE" not in _lines(same_day["number"])[0][5]


def test_spend2_s6c_one_time_vendor_limit_is_compared_in_the_group_currency(env):
    """S6c: a USD line was compared with the rupee limit in raw minor units: 10,000 USD (= 8.5 million INR) is 1,000,000 cents, below Rs 5 lakh in paise."""
    big_usd = _doc(supplier="S-GAMMA", category="RUBBER-SEALS", currency="USD", qty=1, price=10_000_00, day=date(2026, 10, 12), tag="S6G")
    small_usd = _doc(supplier="S-GAMMA", category="RUBBER-SEALS", currency="USD", qty=1, price=50_00, day=date(2026, 10, 12), tag="S6H")
    assert "ONE_TIME_VENDOR" in _lines(big_usd["number"])[0][5]
    assert "ONE_TIME_VENDOR" not in _lines(small_usd["number"])[0][5]


def test_spend2_s6d_off_contract_needs_a_covering_contract_on_the_po_date(env):
    """S6d: OFF_CONTRACT looked at the contract status when the event was processed, ignoring the PO date and the plant."""
    from app.pic.models import Contract, ContractLine
    with tenant_tx(J["tid"]) as s:
        mat = s.execute(select(Material).where(Material.category == "FASTENERS")).scalars().first()
        contract = Contract(tenant_id=J["tid"], number="SP2-CTR-1", type="MASTER", title="Fasteners 2026", supplier_id=J["sup"]["S-ALPHA"], company_code="1000",
                            status="ACTIVE", valid_from=date(2026, 6, 1), valid_to=date(2027, 5, 31), payment_terms="N30", owner_id=J["cm_id"])
        s.add(contract)
        s.flush()
        s.add(ContractLine(tenant_id=J["tid"], contract_id=contract.id, line_no=1, material_id=mat.id, description="fasteners", plant="P1", uom="EA", target_qty=Decimal(1000)))
    covered = _doc(category="FASTENERS", plant="P1", day=date(2026, 9, 12), tag="S6I")
    other_plant = _doc(category="FASTENERS", plant="P2", day=date(2026, 9, 12), tag="S6J")
    before_contract = _doc(category="FASTENERS", plant="P1", day=date(2026, 3, 12), tag="S6K")
    assert "OFF_CONTRACT" in _lines(covered["number"])[0][5]
    assert "OFF_CONTRACT" not in _lines(other_plant["number"])[0][5]
    assert "OFF_CONTRACT" not in _lines(before_contract["number"])[0][5], "the contract did not exist on the PO date"


# ---------------------------------------------------------------- S7.. cube arithmetic
def test_spend2_s7_pending_fx_uses_the_document_date_not_the_period_end(env):
    """S7: a line converted late took the rate of the END of its period; the platform converts new lines at the invoice date."""
    with tenant_tx(J["tid"]) as s:
        s.add(FxRate(tenant_id=J["tid"], from_ccy="EUR", to_ccy="INR", rate=Decimal("90.00"), valid_from=date(2026, 8, 1), source="test"))
        s.add(FxRate(tenant_id=J["tid"], from_ccy="EUR", to_ccy="INR", rate=Decimal("95.00"), valid_from=date(2026, 8, 20), source="test"))
        s.flush()
        line = SpendLine(tenant_id=J["tid"], invoice_line_id=uuid.uuid4(), invoice_ref="SP2-FX-1", po_ref="SP2-FX-PO", supplier_id=J["sup"]["S-BETA"], category="FASTENERS",
                         material_group="FASTENERS", plant="P1", company_code="1000", period="2026-08", amount_minor=100_00, currency="EUR", document_date=date(2026, 8, 10))
        s.add(line)
        s.flush()
        assert spend_cube.convert_pending_fx(s, "INR") == 1
        s.refresh(line)
        assert (line.fx_rate, line.amount_group_minor, line.fx_date) == (Decimal("90.00000000"), 9_000_00, date(2026, 8, 1))


def test_spend2_s8_percentages_are_shares_of_addressable_spend_with_one_rounding(client, login, env):
    """S8: the cube divided contracted spend by ALL spend, the KPIs and the overview by addressable spend; the overview rounded half-even, the cube half-up."""
    with tenant_tx(J["tid"]) as s:
        s.add_all([SpendLine(tenant_id=J["tid"], invoice_line_id=uuid.uuid4(), invoice_ref=f"SP2-PCT-{i}", po_ref="P", supplier_id=J["sup"]["S-BETA"], category=cat,
                             material_group=cat, plant="P1", company_code="1000", period="2025-06", amount_minor=amount, currency="INR", contracted=contracted,
                             addressable=addressable, source="ERP_HISTORY", document_date=date(2025, 6, 10))
                   for i, (cat, amount, contracted, addressable) in enumerate((("FASTENERS", 1225, True, True), ("FASTENERS", 8775, False, True),
                                                                              ("IC-TRANSFER", 10000, True, False)))])
    cube = _cube(["period"], period_from="2025-06", period_to="2025-06", suppliers=["S-BETA"])
    row = cube["rows"][0]
    assert row["addressableMinor"] == 10000 and row["contractedAddressableMinor"] == 1225
    assert row["contractCoveragePct"] == "12.3", "1225 / 10000 = 12.25% rounds half up to 12.3 (not 12.2, and not 20.0 over all spend)"
    assert row["addressablePct"] == "50.0"
    with tenant_tx(J["tid"]) as s:
        assert spend.portfolio(s, "2025-06", "2025-06")["contractedMinor"] >= 1225 and spend._pct(1225, 10000) == "12.3"


def test_spend2_s9_hhi_uses_parent_groups_and_ignores_net_negative_suppliers(env):
    """S9: HHI was computed on child records (a group split in two looked unconcentrated) and a net-credit supplier produced shares above 100%."""
    assert spend.hhi_of({"a": 5000, "b": 5000}) == Decimal(5000)
    assert spend.hhi_of({"a": 10000, "b": -4000}) == Decimal(10000), "the supplier with a net credit has no share"
    assert spend.hhi_of({}) == 0 and spend.hhi_of({"a": -5}) == 0
    _doc(supplier="S-PARENT", category="RUBBER-SEALS", day=date(2026, 9, 14), qty=5, price=1000_00, tag="S9A")
    _doc(supplier="S-CHILD", category="RUBBER-SEALS", day=date(2026, 9, 14), qty=5, price=1000_00, tag="S9B")
    with tenant_tx(J["tid"]) as s:
        view = spend.suppliers_view(s)
        rubber = next(c for c in view["concentration"] if c["category"] == "RUBBER-SEALS")
        assert rubber["suppliers"] >= 1 and rubber["hhi"] >= rubber["hhiChild"], "rolled up to the parent, the group is more concentrated than its children"


def test_spend2_s10_filters_are_validated_and_ties_are_ordered(client, login, env):
    h = _h(login, "cm")
    for query, code in (("period_from=2026-13", "INVALID_PERIOD"), ("period_from=2026-9", "INVALID_PERIOD"), ("period_from=2026-10&period_to=2026-01", "INVALID_PERIOD"),
                        ("currency=US", "INVALID_FILTER"), ("dims=nothing", "INVALID_DIMENSION"), ("period_to=2026-01'%3B%20DROP%20TABLE%20x", "INVALID_PERIOD")):
        _problem(client.get(f"/v1/spend/analysis?{query}", headers=h), 400 if code == "INVALID_DIMENSION" else 422, code)
    assert client.get("/v1/spend/analysis?limit=0", headers=h).status_code == 422
    many = ",".join(f"S{n}" for n in range(201))
    _problem(client.get(f"/v1/spend/analysis?supplier={many}", headers=h), 422, "INVALID_FILTER")
    injection = client.get("/v1/spend/analysis?dims=supplier&supplier=S-ALPHA'%20OR%20'1'%3D'1", headers=h)
    assert injection.status_code == 200 and injection.json()["rows"] == [], "a value is data, never SQL"
    same = [client.get("/v1/spend/analysis?dims=period,category&limit=7", headers=h).json()["rows"] for _ in range(2)]
    assert same[0] == same[1]


def test_spend2_s11_a_never_built_cube_is_built_by_the_scheduled_refresh(env):
    """S11: refresh_spend_views(dirty_only=True) on a cube that was never built refreshed nothing (the admin button and the job both pass dirty_only)."""
    sc = kit.setup_tenant(CODE + "B", "Never Built Ltd", "GENERAL", company=("1000", "Never Built Ltd", GSTIN), plants=[("P1", "P", "29")], cost_objects=[],
                          holidays=[], domain=f"b.{DOMAIN}", role_user={})
    with tenant_tx(sc.tenant_id) as s:
        s.add(Supplier(tenant_id=sc.tenant_id, code="NB1", legal_name="Never Built Supplier", status="QUALIFIED"))
        s.flush()
        sid = s.execute(select(Supplier.id)).scalar_one()
        s.add(SpendLine(tenant_id=sc.tenant_id, invoice_line_id=uuid.uuid4(), invoice_ref="NB-1", po_ref="NB", supplier_id=sid, category="MRO", material_group="MRO", plant="P1",
                        company_code="1000", period="2026-08", amount_minor=500, currency="INR"))
    result = spend_cube.refresh_spend_views(sc.tenant_id, dirty_only=True)
    assert result["cube"]["mode"] == "FULL" and result["cube"]["lines"] == 1


# ---------------------------------------------------------------- S12 classification
def test_spend2_s12_credit_note_lines_never_enter_the_steward_queue_and_follow_a_reclassification(client, login, env):
    ids = _doc(category="NOSUCHWORDS", material=False, day=date(2026, 8, 14), qty=4, price=1000_00, tag="S12")
    _note(ids, qty="1", day=date(2026, 8, 28))
    _relay()
    with tenant_tx(J["tid"]) as s:
        reviews = s.execute(select(spend.ClassificationReview).where(spend.ClassificationReview.invoice_ref == ids["number"])).scalars().all()
        assert len(reviews) == 1, "only the invoice line is reviewed"
    h = _h(login, "cm")
    queue = client.get("/v1/spend/classification-queue?status=OPEN&limit=500", headers=h).json()
    review = next(i for i in queue["items"] if i["invoice_ref"] == ids["number"])
    done = client.post(f"/v1/spend/classification-reviews/{review['id']}/decision", json={"category": "FASTENERS", "comment": "checked drawing"}, headers=h)
    assert done.status_code == 200 and done.json()["status"] == "RECLASSIFIED"
    assert {r[4] for r in _lines(ids["number"])} == {"FASTENERS"}, "the credit note line moved with its invoice line"
    again = client.post(f"/v1/spend/classification-reviews/{review['id']}/decision", json={"category": "FASTENERS"}, headers=h)
    _problem(again, 409, "ILLEGAL_TRANSITION")
    cube = _cube(["category"], period_from="2026-08", period_to="2026-08", categories=["FASTENERS"])
    assert cube["totals"]["creditNoteMinor"] <= -1_000_00 and cube["freshness"]["stale"] is False


def test_spend2_s13_hit_dispositions_are_refused_twice_and_need_a_reason_code(client, login, env):
    ids = _doc(day=date(2026, 8, 3), qty=10, price=1000_00, received=0, tag="S13")
    with tenant_tx(J["tid"]) as s:
        hit_id = str(s.execute(select(MaverickHit.id).where(MaverickHit.invoice_ref == ids["number"])).scalar_one())
    h = _h(login, "fin")
    body = {"disposition": "FALSE_POSITIVE", "comment": "the GR was posted a day later"}
    _problem(client.post(f"/v1/spend/maverick-hits/{hit_id}/disposition", json=body, headers=h), 422, "REASON_CODE_REQUIRED")
    _problem(client.post(f"/v1/spend/maverick-hits/{hit_id}/disposition", json={**body, "reason_code": "NONSENSE"}, headers=h), 422, "REASON_CODE_REQUIRED")
    ok = client.post(f"/v1/spend/maverick-hits/{hit_id}/disposition", json={**body, "reason_code": "DATA_ERROR"}, headers=h)
    assert ok.status_code == 200 and ok.json()["status"] == "DISPOSED" and ok.json()["reason_code"] == "DATA_ERROR"
    _problem(client.post(f"/v1/spend/maverick-hits/{hit_id}/disposition", json={**body, "reason_code": "DATA_ERROR"}, headers=h), 409, "ILLEGAL_TRANSITION")


def test_spend2_s14_a_category_plan_is_never_approved_by_its_owner_or_submitter(client, login, env):
    ph, ph2 = _h(login, "ph"), _h(login, "ph2")
    _doc(category="FASTENERS", day=date(2026, 10, 3), qty=100, price=1000_00, supplier="S-BETA", tag="S14")
    with tenant_tx(J["tid"]) as s:
        s.info["principal"] = _principal(s, "ph")
        plans = spend.generate_plans(s, "2026-27", s.info["principal"].user_id)
        number = next(p.number for p in plans if p.category == "FASTENERS")
    own = client.post(f"/v1/category-plans/{number}/approve", json={}, headers=ph)
    _problem(own, 409, "SOD_CONFLICT")
    ok = client.post(f"/v1/category-plans/{number}/approve", json={"comment": "checked"}, headers=ph2)
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVED"
    _problem(client.post(f"/v1/category-plans/{number}/approve", json={}, headers=ph2), 409, "ILLEGAL_TRANSITION")


def _principal(s, local):
    from app.pic.platform.auth import Principal, scopes_for
    u = s.execute(select(AppUser).where(AppUser.email == _email(local))).scalar_one()
    return Principal(user_id=u.id, tenant_id=J["tid"], tenant_code=CODE, email=u.email, name=u.full_name, roles=list(u.roles), scopes=scopes_for(list(u.roles), s),
                     attributes=dict(u.attributes or {}))


def test_spend2_s15_empty_and_single_line_cubes_and_non_po_invoices(client, login, env):
    sc = kit.setup_tenant(CODE + "C", "Empty Cube Ltd", "GENERAL", company=("1000", "Empty Cube Ltd", GSTIN), plants=[("P1", "P", "29")], cost_objects=[], holidays=[],
                          domain=f"c.{DOMAIN}", role_user={})
    with tenant_tx(sc.tenant_id) as s:
        s.info["principal"] = None
        empty = spend_cube.cube(s, ["category"])
        assert empty["rows"] == [] and empty["totalMinor"] == 0 and empty["totals"]["contractCoveragePct"] == "0"
        assert spend.overview(s)["totalMinor"] == 0 and spend.forecast(s)["series"] == [] and spend_quality.assess(s)["score"] > 0
        assert spend_analytics.pareto(s)["count"] == 0 and spend_analytics.comparison(s, ["category"])["rows"] == []
    # an invoice line without a PO line does not crash the consumer
    ids = _doc(day=date(2026, 8, 3), qty=2, price=700_00, tag="S15", feed=False)
    with tenant_tx(J["tid"]) as s:
        inv = s.get(Invoice, ids["invoice"])
        line = s.get(InvoiceLine, ids["invoice_line"])
        line.po_line_id = None
        s.flush()
        assert spend_feed.feed_invoice(s, inv) == 1
    rows = _lines(ids["number"])
    assert rows[0][3] == 1_400_00 and rows[0][0] == "INVOICE"


# ================================================================ workflows and new capabilities
def _review_of(invoice_number: str):
    with tenant_tx(J["tid"]) as s:
        r = s.execute(select(spend.ClassificationReview).where(spend.ClassificationReview.invoice_ref == invoice_number)).scalar_one()
        return str(r.id), r.status, r.value_group_minor, r.due_at


def _decide(client, login, who, review_id, category, **extra):
    return client.post(f"/v1/spend/classification-reviews/{review_id}/decision", json={"category": category, **extra}, headers=_h(login, who))


def test_spend2_w1_reclassification_above_the_value_needs_two_stewards_who_agree(client, login, env):
    ids = _doc(category="QWERTYKIT", material=False, day=date(2026, 9, 2), qty=10, price=30_000_000, tag="W1")        # Rs 30 lakh, above the Rs 25 lakh four-eyes value
    rid, status, value, due = _review_of(ids["number"])
    assert status == "OPEN" and value >= 250_000_000 and due is not None
    first = _decide(client, login, "cm", rid, "FASTENERS", comment="drawing checked", reason="checked")
    assert first.status_code == 200 and first.json()["status"] == "PENDING_SECOND"
    assert {r[4] for r in _lines(ids["number"])} != {"FASTENERS"}, "nothing changed on the line after the first decision"
    _problem(_decide(client, login, "cm", rid, "FASTENERS"), 409, "SOD_CONFLICT")
    disagree = _decide(client, login, "cm2", rid, "RUBBER-SEALS")
    assert disagree.status_code == 200 and disagree.json()["status"] == "OPEN", "a different category reopens the review"
    assert _decide(client, login, "cm", rid, "FASTENERS").json()["status"] == "PENDING_SECOND"
    done = _decide(client, login, "cm2", rid, "FASTENERS", comment="confirmed")
    assert done.status_code == 200 and done.json()["status"] == "RECLASSIFIED" and {r[4] for r in _lines(ids["number"])} == {"FASTENERS"}
    # accepting the agent's own proposal is one decision at any value
    big = _doc(category="QWERTYKIT", material=False, day=date(2026, 9, 3), qty=10, price=30_000_000, tag="W1B")
    rid2, *_ = _review_of(big["number"])
    with tenant_tx(J["tid"]) as s:
        proposed = s.get(spend.ClassificationReview, uuid.UUID(rid2)).proposed_category
    assert _decide(client, login, "cm", rid2, proposed).json()["status"] == "ACCEPTED"
    other = _doc(category="QWERTYKIT", material=False, day=date(2026, 9, 3), qty=1, price=1000, tag="W1C")
    _problem(_decide(client, login, "buyer", _review_of(other["number"])[0], "FASTENERS"), 403)


def test_spend2_w2_bulk_reclassification_with_keyword_learning_and_conflict_guard(client, login, env):
    refs = [_doc(category="ZORBAXWIDGET", material=False, day=date(2026, 9, 4), qty=2, price=500_00, tag=f"W2{c}")["number"] for c in "ABC"]
    h = _h(login, "cm")
    with tenant_tx(J["tid"]) as s:
        s.info["principal"] = _principal(s, "cm")
        before = spend.classify_text(s, "zorbaxwidget bracket kit", None)
    assert before[0] == "UNCLASSIFIED"
    r = client.post("/v1/spend/classification-reviews/bulk", json={"category": "FASTENERS", "comment": "zorbax widgets are fasteners", "text": "zorbaxwidget",
                                                                   "learn_keyword": "zorbaxwidget"}, headers=h)
    assert r.status_code == 200 and r.json()["selected"] >= 3 and all(x["status"] == "RECLASSIFIED" for x in r.json()["results"]), r.text
    assert {l[4] for ref in refs for l in _lines(ref)} == {"FASTENERS"}
    with tenant_tx(J["tid"]) as s:
        channels = {r.channel for r in s.execute(select(spend.ClassificationReview).where(spend.ClassificationReview.invoice_ref.in_(refs))).scalars()}
    assert channels == {"BULK"}, "the channel is kept after the decision (decide_review re-reads the row under its lock)"
    with tenant_tx(J["tid"]) as s:
        s.info["principal"] = _principal(s, "cm")
        after = spend.classify_text(s, "zorbaxwidget bracket kit", None)
        assert after[0] == "FASTENERS" and after[1] > before[1], "the classifier learned the word"
        node = s.execute(select(TaxonomyNode).where(TaxonomyNode.code == "FASTENERS")).scalar_one()
        assert "zorbaxwidget" in node.keywords
    again = _doc(category="ZORBAXWIDGET", material=False, day=date(2026, 9, 5), qty=2, price=500_00, tag="W2D")
    other = _doc(category="OBSCUREPART", material=False, day=date(2026, 9, 5), qty=2, price=500_00, tag="W2E")
    rid, *_ = _review_of(other["number"])
    _problem(_decide(client, login, "cm", rid, "ALU-DIECAST", learn_keyword="bolt"), 409, "KEYWORD_CONFLICT")
    _problem(_decide(client, login, "cm", rid, "ALU-DIECAST", learn_keyword="two words"), 422, "INVALID_KEYWORD")
    _problem(client.post("/v1/spend/classification-reviews/bulk", json={"category": "FASTENERS", "comment": "no selection given"}, headers=h), 422, "SELECTION_REQUIRED")
    _problem(client.post("/v1/spend/classification-reviews/bulk", json={"category": "FASTENERS", "comment": "buyer tries", "text": "obscure"}, headers=_h(login, "buyer")), 403)


def test_spend2_w3_the_queue_shows_value_age_and_sla(client, login, env):
    ids = _doc(category="SLATESTITEM", material=False, day=date(2026, 9, 6), qty=1, price=900_00, tag="W3")
    h = _h(login, "cm")
    queue = client.get("/v1/spend/classification-queue?status=OPEN&sort=value&limit=500", headers=h).json()
    item = next(i for i in queue["items"] if i["invoice_ref"] == ids["number"])
    assert item["overdue"] is False and item["dueAt"] and item["fourEyes"] is False and item["valueMinor"] == 900_00
    values = [i["valueMinor"] for i in queue["items"]]
    assert values == sorted(values, reverse=True)
    try:
        clock.set_pinned(at(TODAY + timedelta(days=9), 10))
        late = client.get("/v1/spend/classification-queue?status=OPEN&overdue=true&limit=500", headers=h).json()
        assert ids["number"] in {i["invoice_ref"] for i in late["items"]} and late["summary"]["overdue"] >= 1 and late["summary"]["oldestDays"] >= 9
    finally:
        clock.set_pinned(at(TODAY, 10))
    _problem(client.get("/v1/spend/classification-queue?sort=nonsense", headers=h), 422)


def test_spend2_w4_maverick_rules_are_effective_dated_versions(client, login, env):
    admin = _h(login, "admin")
    future = (TODAY + timedelta(days=30)).isoformat()
    ok = client.post("/v1/spend/maverick-rules/NON_CATALOGUE/versions", json={"effective_from": future, "reason": "catalogue not ready until December", "active": False,
                                                                              "sla_days": 20}, headers=admin)
    assert ok.status_code == 201 and ok.json()["change"] == {"active": False, "slaDays": 20}
    now = {r["code"]: r for r in client.get("/v1/spend/maverick-rules", headers=_h(login, "cm")).json()["rules"]}
    later = {r["code"]: r for r in client.get(f"/v1/spend/maverick-rules?on={future}", headers=_h(login, "cm")).json()["rules"]}
    assert now["NON_CATALOGUE"]["active"] is True and later["NON_CATALOGUE"]["active"] is False and later["NON_CATALOGUE"]["slaDays"] == 20
    assert later["NON_CATALOGUE"]["versions"] and len(later) == 9
    same_day = client.post("/v1/spend/maverick-rules/NON_CATALOGUE/versions", json={"effective_from": future, "reason": "again the same day", "active": True}, headers=admin)
    _problem(same_day, 409, "RULE_VERSION_CONFLICT")
    _problem(client.post("/v1/spend/maverick-rules/NON_CATALOGUE/versions", json={"effective_from": future, "reason": "cm is not admin", "active": True}, headers=_h(login, "cm")), 403)
    _problem(client.post("/v1/spend/maverick-rules/NOPE/versions", json={"effective_from": future, "reason": "no such rule", "active": True}, headers=admin), 404)
    _problem(client.post("/v1/spend/maverick-rules/SPLIT_PO/versions", json={"effective_from": future, "reason": "bad role value", "owner_role": "JANITOR"}, headers=admin), 422, "INVALID_OWNER_ROLE")
    # a rule retired from today stops raising hits
    retire = client.post("/v1/spend/maverick-rules/OVER_INVOICED/versions", json={"effective_from": TODAY.isoformat(), "reason": "tolerance under review", "active": False}, headers=admin)
    assert retire.status_code == 201
    today_doc = _doc(day=TODAY, qty=10, price=1000_00, invoiced_qty=13, invoiced_minor=13 * 1000_00, tag="W4")
    earlier_doc = _doc(day=date(2026, 9, 8), qty=10, price=1000_00, invoiced_qty=13, invoiced_minor=13 * 1000_00, tag="W4B")
    assert "OVER_INVOICED" not in _lines(today_doc["number"])[0][5], "the version applies to documents dated from its effective date"
    assert "OVER_INVOICED" in _lines(earlier_doc["number"])[0][5], "and not to earlier ones"
    with tenant_tx(J["tid"]) as s:
        assert s.execute(select(spend.MaverickRule.active).where(spend.MaverickRule.code == "OVER_INVOICED")).scalar() is True, "the baseline row is never edited"
    # the generic rules API validates the rule sets too
    bad = client.post("/v1/admin/rules", json={"key": "MAVERICK-RULES", "version": "bad-1", "effective_from": future, "body": {"rules": {"SPLIT_PO": {"slaDays": 500}}}}, headers=admin)
    _problem(bad, 422, "RULE_INVALID")
    bad = client.post("/v1/admin/rules", json={"key": "SPEND-GOVERNANCE", "version": "bad-2", "effective_from": future, "body": {"classificationThreshold": "1.5"}}, headers=admin)
    _problem(bad, 422, "RULE_INVALID")


def test_spend2_w5_hit_lifecycle_recovery_resolution_and_sla_escalation(client, login, env):
    ids = _doc(day=date(2026, 9, 9), qty=10, price=1000_00, received=0, tag="W5")
    with tenant_tx(J["tid"]) as s:
        hit = s.execute(select(MaverickHit).where(MaverickHit.invoice_ref == ids["number"])).scalar_one()
        hit_id, due, number = str(hit.id), hit.due_at, hit.number
        assert hit.rule_code == "NO_GOODS_RECEIPT" and (due - clock.now()).days in (2, 3)         # Critical: 3 days
    fin = _h(login, "fin")
    rec = client.post(f"/v1/spend/maverick-hits/{hit_id}/disposition", json={"disposition": "RECOVERY", "comment": "debit note requested from the supplier"}, headers=fin)
    assert rec.status_code == 200 and rec.json()["status"] == "RECOVERY_OPEN"
    _problem(client.post(f"/v1/spend/maverick-hits/{hit_id}/resolve", json={"recovered_minor": 99_999_999_99, "note": "far too much money"}, headers=fin), 422, "RECOVERY_EXCEEDS_HIT")
    done = client.post(f"/v1/spend/maverick-hits/{hit_id}/resolve", json={"recovered_minor": 8_000_00, "note": "credit note CN-77 received"}, headers=fin)
    assert done.status_code == 200 and done.json()["status"] == "RESOLVED" and done.json()["recovered_minor"] == 8_000_00
    _problem(client.post(f"/v1/spend/maverick-hits/{hit_id}/resolve", json={"recovered_minor": 1, "note": "second time"}, headers=fin), 409, "ILLEGAL_TRANSITION")
    work = client.get("/v1/spend/maverick/worklist?status=RESOLVED&limit=500", headers=fin).json()
    row = next(h for h in work["hits"] if h["number"] == number)
    assert row["lifecycle"] == "RESOLVED" and work["summary"]["recoveredMinor"] >= 8_000_00
    # escalation of an open hit past its SLA, one level at a time, at most twice
    ids2 = _doc(day=date(2026, 9, 9), qty=10, price=1000_00, invoiced_qty=20, invoiced_minor=20 * 1000_00, tag="W5B")
    with tenant_tx(J["tid"]) as s:
        s.info["principal"] = _principal(s, "fin")
        hit2 = s.execute(select(MaverickHit).where(MaverickHit.invoice_ref == ids2["number"], MaverickHit.rule_code == "OVER_INVOICED")).scalar_one()
        assert hit2.escalation_level == 0 and hit2.owner_role == "FINANCE_CONTROLLER"
        assert [h for h in spend.escalate_overdue(s, hit2.due_at - timedelta(minutes=1)) if h.id == hit2.id] == []
        first = [h for h in spend.escalate_overdue(s, hit2.due_at + timedelta(hours=1)) if h.id == hit2.id]
        assert len(first) == 1 and hit2.escalation_level == 1 and hit2.escalated_to_role == "CPO" and hit2.owner_role == "CPO"
        again = [h for h in spend.escalate_overdue(s, hit2.due_at - timedelta(hours=1)) if h.id == hit2.id]
        assert again == [], "the new due date is in the future"
        second = [h for h in spend.escalate_overdue(s, hit2.due_at + timedelta(days=30)) if h.id == hit2.id]
        assert len(second) == 1 and hit2.escalation_level == 2
        assert [h for h in spend.escalate_overdue(s, hit2.due_at + timedelta(days=60)) if h.id == hit2.id] == []
    from app.pic.services import jobs
    assert {"spend-cube-refresh", "spend-sla", "spend-quality", "spend-forecast-snapshot"} <= set(jobs.REGISTRY)


def test_spend2_w6_repeat_offenders_and_savings_at_risk(client, login, env):
    for n in range(3):
        _doc(supplier="S-GAMMA", day=date(2026, 9, 10 + n), qty=10, price=1000_00, received=0, tag=f"W6{n}")
    data = client.get("/v1/spend/maverick/repeat-offenders?months=12&min_hits=3", headers=_h(login, "cm")).json()
    gamma = next(r for r in data["suppliers"] if r["supplier"] == "S-GAMMA")
    assert gamma["hits"] >= 3 and "NO_GOODS_RECEIPT" in gamma["rules"] and gamma["name"] == "Gamma Gaskets Pvt Ltd"
    _problem(client.get("/v1/spend/maverick/repeat-offenders?months=0", headers=_h(login, "cm")), 422)
    summary = client.get("/v1/spend/maverick/worklist", headers=_h(login, "cm")).json()["summary"]
    assert summary["open"] >= 3 and "openByOwnerRole" in summary and summary["overdue"] >= 0


def _supplier_with(s, code, name, pan=None):
    sup = Supplier(tenant_id=J["tid"], code=code, legal_name=name, status="QUALIFIED", pan_hash=pan)
    s.add(sup)
    s.flush()
    return sup


def test_spend2_w7_duplicate_clusters_merge_proposal_needs_a_second_steward(client, login, env):
    with tenant_tx(J["tid"]) as s:
        _supplier_with(s, "D-DELTA1", "Delta Dies Pvt Ltd", pan="HASH-DELTA")
        _supplier_with(s, "D-DELTA2", "Delta Dies Private Limited", pan="HASH-DELTA")
        _supplier_with(s, "D-ECHO1", "Echo Engineering Works", None)
        _supplier_with(s, "D-ECHO2", "Echo Engineering Works Limited", None)
        _supplier_with(s, "D-PLANT1", "Plant 1 Services Pvt Ltd", None)
        _supplier_with(s, "D-PLANT2", "Plant 2 Services Pvt Ltd", None)
        _supplier_with(s, "D-ZED", "Zed Zinc Castings", None)
    h, st1, st2 = _h(login, "cm"), _h(login, "steward"), _h(login, "steward2")
    scan = client.post("/v1/spend/duplicates/scan", headers=st1)
    assert scan.status_code == 200 and scan.json()["new"] >= 2
    clusters = client.get("/v1/spend/duplicates", headers=h).json()["clusters"]
    by_codes = {tuple(sorted(m["code"] for m in c["suppliers"])): c for c in clusters}
    assert ("D-DELTA1", "D-DELTA2") in by_codes and by_codes[("D-DELTA1", "D-DELTA2")]["score"] == 1.0 and "same PAN" in by_codes[("D-DELTA1", "D-DELTA2")]["reason"]
    assert ("D-ECHO1", "D-ECHO2") in by_codes and by_codes[("D-ECHO1", "D-ECHO2")]["score"] >= 0.92
    assert not any({"D-PLANT1", "D-PLANT2"} <= {m["code"] for m in c["suppliers"]} for c in clusters), "Plant 1 and Plant 2 are different suppliers"
    key = by_codes[("D-DELTA1", "D-DELTA2")]["key"]
    _problem(client.post(f"/v1/spend/duplicates/{key}/propose-merge", json={"survivor": "D-OTHER", "note": "wrong survivor"}, headers=st1), 422, "SURVIVOR_NOT_IN_CLUSTER")
    _problem(client.post(f"/v1/spend/duplicates/{key}/propose-merge", json={"survivor": "D-DELTA1", "note": "buyer tries"}, headers=_h(login, "buyer")), 403)
    prop = client.post(f"/v1/spend/duplicates/{key}/propose-merge", json={"survivor": "D-DELTA1", "note": "same PAN, same bank"}, headers=st1)
    assert prop.status_code == 201 and prop.json()["status"] == "PROPOSED"
    proposal = prop.json()["proposal_number"]
    assert not [t for t in client.get("/v1/tasks", headers=st1).json() if t["object_ref"] == proposal], "the proposer cannot work the approval"
    tasks = [t for t in client.get("/v1/tasks", headers=st2).json() if t["object_ref"] == proposal]
    assert len(tasks) == 1
    _problem(client.post(f"/v1/spend/duplicates/{key}/dismiss", json={"note": "changed my mind now"}, headers=st1), 409, "ILLEGAL_TRANSITION")
    done = client.post(f"/v1/tasks/{tasks[0]['id']}/complete", json={"decision": "APPROVE", "comment": "confirmed against the GST portal"}, headers=st2)
    assert done.status_code == 200, done.text
    with tenant_tx(J["tid"]) as s:
        child = s.execute(select(Supplier).where(Supplier.code == "D-DELTA2")).scalar_one()
        survivor = s.execute(select(Supplier).where(Supplier.code == "D-DELTA1")).scalar_one()
        assert child.parent_supplier_id == survivor.id and survivor.parent_supplier_id is None, "linked under the survivor, nothing merged or deleted"
        assert s.execute(select(func.count()).select_from(Supplier).where(Supplier.code.in_(("D-DELTA1", "D-DELTA2")))).scalar() == 2
    other = by_codes[("D-ECHO1", "D-ECHO2")]["key"]
    assert client.post(f"/v1/spend/duplicates/{other}/dismiss", json={"note": "different legal entities (GSTIN differs)"}, headers=st1).status_code == 200
    after = client.get("/v1/spend/duplicates", headers=h).json()["clusters"]
    assert not any({"D-ECHO1", "D-ECHO2"} <= {m["code"] for m in c["suppliers"]} for c in after), "a dismissed cluster does not come back"


def test_spend2_w8_category_plan_validation_edit_submission_revision_and_versions(client, login, env):
    cm, cm2, ph, ph2 = _h(login, "cm"), _h(login, "cm2"), _h(login, "ph"), _h(login, "ph2")
    _doc(category="RUBBER-SEALS", supplier="S-GAMMA", day=date(2026, 10, 4), qty=200, price=1000_00, tag="W8")
    with tenant_tx(J["tid"]) as s:
        s.info["principal"] = _principal(s, "cm")
        plans = spend.generate_plans(s, "2027-28", s.info["principal"].user_id)
        plan = next(p for p in plans if p.category == "RUBBER-SEALS")
        number, budget, target, addressable = plan.number, plan.budget_minor, plan.savings_target_minor, plan.addressable_minor
        assert plan.addressable_minor == plan.spend_minor and plan.wave_plan and sum(plan.savings_by_lever.values()) == plan.savings_target_minor
        assert all(w["start"] <= w["end"] and w["start"] >= "2027-04-01" for w in plan.wave_plan)
    detail = client.get(f"/v1/category-plans/{number}", headers=cm).json()
    assert detail["validation"] == [] and detail["versions"] == [{"number": number, "version": 1, "status": "DRAFT"}]
    for patch, text_ in (({"savings_target_minor": addressable}, "above"), ({"levers": ["Magic wand"]}, "lever catalogue"),
                         ({"wave_plan": [{"name": "x", "start": "2027-06-01", "end": "2027-05-01"}]}, "ends before"),
                         ({"wave_plan": [{"name": "x", "start": "bad", "end": "2027-05-01"}]}, "start and an end"),
                         ({"wave_plan": [{"name": "x", "start": "2027-06-01", "end": "2027-06-02"}]}, "shorter than"),
                         ({"savings_by_lever": {"Not a lever": 5}}, "levers the plan does not use")):
        bad = client.patch(f"/v1/category-plans/{number}", json=patch, headers=cm)
        _problem(bad, 422, "INVALID_PLAN")
        assert text_ in bad.json()["detail"], (patch, bad.json())
    assert client.patch(f"/v1/category-plans/{number}", json={"budget_minor": -1}, headers=cm).status_code == 422
    _problem(client.patch(f"/v1/category-plans/{number}", json={"budget_minor": budget}, headers=cm2), 403)            # not the owner
    ok = client.patch(f"/v1/category-plans/{number}", json={"savings_target_minor": target // 2}, headers=cm)
    assert ok.status_code == 200 and ok.json()["savings_target_minor"] == target // 2 and sum(ok.json()["savings_by_lever"].values()) == target // 2
    _problem(client.post(f"/v1/category-plans/{number}/submit", json={}, headers=cm2), 403)
    sub = client.post(f"/v1/category-plans/{number}/submit", json={}, headers=cm)
    assert sub.status_code == 200 and sub.json()["status"] == "IN_APPROVAL"
    _problem(client.patch(f"/v1/category-plans/{number}", json={"budget_minor": budget}, headers=cm), 409, "ILLEGAL_TRANSITION")
    _problem(client.post(f"/v1/category-plans/{number}/reject", json={"comment": "owner rejecting own plan"}, headers=cm), 403)
    tasks = [t for t in client.get("/v1/tasks", headers=ph).json() if t["object_ref"] == number]
    assert len(tasks) == 1
    done = client.post(f"/v1/tasks/{tasks[0]['id']}/complete", json={"decision": "APPROVE", "comment": "go"}, headers=ph)
    assert done.status_code == 200, done.text
    assert client.get(f"/v1/category-plans/{number}", headers=cm).json()["status"] == "APPROVED"
    _problem(client.post(f"/v1/category-plans/{number}/revise", json={"comment": "x"}, headers=cm), 422)
    rev = client.post(f"/v1/category-plans/{number}/revise", json={"comment": "budget re-cut after the Q2 review"}, headers=cm)
    assert rev.status_code == 201 and rev.json()["version"] == 2 and rev.json()["status"] == "DRAFT" and rev.json()["number"] != number
    _problem(client.post(f"/v1/category-plans/{number}/revise", json={"comment": "second revision at once"}, headers=cm), 409, "REVISION_OPEN")
    rejected = client.post(f"/v1/category-plans/{rev.json()['number']}/reject", json={"comment": "budget still too high"}, headers=ph2)
    assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
    _problem(client.post(f"/v1/category-plans/{rev.json()['number']}/approve", json={"comment": "after rework"}, headers=ph2), 409, "ILLEGAL_TRANSITION")
    again = client.patch(f"/v1/category-plans/{rev.json()['number']}", json={"budget_minor": budget}, headers=cm)
    assert again.status_code == 200 and again.json()["status"] == "DRAFT"
    assert client.post(f"/v1/category-plans/{rev.json()['number']}/approve", json={"comment": "approved after rework"}, headers=ph2).status_code == 200
    final = client.get(f"/v1/category-plans/{number}", headers=cm).json()
    assert final["status"] == "SUPERSEDED" and [v["status"] for v in final["versions"]] == ["SUPERSEDED", "APPROVED"]
    links = client.get(f"/v1/category-plans/{rev.json()['number']}/pipeline-links", headers=cm).json()
    assert links["category"] == "RUBBER-SEALS" and "sourcingEvents" in links
    assert client.get("/v1/category-plans/NO-SUCH", headers=cm).status_code == 404


def test_spend2_w9_analytics_comparisons_pareto_structure_and_savings_potential(client, login, env):
    h = _h(login, "cm")
    cmp_ = client.get("/v1/spend/comparison?dims=category&limit=20", headers=h).json()
    assert cmp_["anchor"] == "2026-10" and cmp_["windows"]["ytd"] == ["2026-04", "2026-10"] and cmp_["windows"]["priorYtd"] == ["2025-04", "2025-10"]
    assert cmp_["windows"]["lastQuarter"] == ["2026-07", "2026-09"] and cmp_["windows"]["prevQuarter"] == ["2026-04", "2026-06"]
    assert cmp_["totals"]["runRateAnnualMinor"] >= 0 and all(r["sharePct"] is not None for r in cmp_["rows"])
    mar = client.get("/v1/spend/comparison?anchor=2026-03", headers=h).json()
    assert mar["windows"]["ytd"] == ["2025-04", "2026-03"] and mar["windows"]["lastQuarter"] == ["2026-01", "2026-03"], "March is the last month of the fiscal year"
    apr = client.get("/v1/spend/comparison?anchor=2026-04", headers=h).json()
    assert apr["windows"]["ytd"] == ["2026-04", "2026-04"] and apr["windows"]["lastQuarter"] == ["2026-01", "2026-03"]
    _problem(client.get("/v1/spend/comparison?anchor=2026-4", headers=h), 422)
    _problem(client.get("/v1/spend/comparison?dims=bogus", headers=h), 400, "INVALID_DIMENSION")
    pareto = client.get("/v1/spend/pareto?by=supplier", headers=h).json()
    assert pareto["classes"]["A"]["count"] >= 1 and sum(c["count"] for c in pareto["classes"].values()) == pareto["count"]
    assert abs(sum(Decimal(c["spendPct"]) for c in pareto["classes"].values()) - 100) <= Decimal("0.3")
    assert pareto["rows"][0]["class"] == "A" and Decimal(pareto["rows"][-1]["cumulativePct"]) >= Decimal("99.9") and pareto["tailCount"] == pareto["classes"]["C"]["count"]
    structure = client.get("/v1/spend/category-structure", headers=h).json()
    assert all(r["hhi"] <= 10000 and r["suppliers"] >= 1 for r in structure["rows"])
    potential = client.get("/v1/spend/savings-potential", headers=h).json()
    assert set(potential["byLever"]) == {"CONSOLIDATION", "CONTRACT_COVERAGE", "PRICE_RECOVERY"} and potential["totalMinor"] == sum(potential["byLever"].values())
    summary = client.get("/v1/spend/summary?fiscal_year=2026-27", headers=h).json()
    assert summary["fiscalYear"] == "2026-27" and summary["periods"] == ["2026-04", "2027-03"]
    assert summary["spendMinor"] == summary["invoicedMinor"] + summary["debitNoteMinor"] + summary["creditNoteMinor"]
    _problem(client.get("/v1/spend/summary?fiscal_year=26-27", headers=h), 422)


def test_spend2_w10_lines_drill_has_stable_cursors_and_lineage(client, login, env):
    h = _h(login, "cm")
    seen, cursor, pages, total = [], None, 0, None
    while pages < 40:
        url = "/v1/spend/lines?limit=7&period_from=2026-08&period_to=2026-09" + (f"&cursor={cursor}" if cursor else "")
        page = client.get(url, headers=h).json()
        total = page["matching"]
        seen += [l["lineId"] for l in page["lines"]]
        cursor, pages = page["nextCursor"], pages + 1
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == total, "every line once, none twice"
    first = client.get("/v1/spend/lines?limit=500&period_from=2026-08&period_to=2026-08&supplier=S-ALPHA", headers=h).json()
    assert first["matching"] == len(first["lines"]) and all(l["lineage"]["invoice"] for l in first["lines"])
    credit = client.get("/v1/spend/lines?document_type=CREDIT_NOTE&limit=50", headers=h).json()
    assert credit["lines"] and all(l["amountMinor"] < 0 and l["documentRef"] for l in credit["lines"])
    _problem(client.get("/v1/spend/lines?cursor=not-a-cursor", headers=h), 422, "INVALID_CURSOR")
    _problem(client.get("/v1/spend/lines?limit=501", headers=h), 422)
    _problem(client.get("/v1/spend/lines?document_type=PO", headers=h), 422, "INVALID_DOCUMENT_TYPE")


def test_spend2_w11_export_is_hashed_audited_and_safe_in_a_spreadsheet(client, login, env):
    import hashlib
    h = _h(login, "cm")
    r = client.get("/v1/spend/export?kind=cube&dims=category,period&period_from=2026-08&period_to=2026-09", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    assert hashlib.sha256(r.content).hexdigest() == r.headers["X-Content-SHA256"] and int(r.headers["X-Row-Count"]) == len(r.text.strip().splitlines()) - 1
    assert r.text.splitlines()[0].startswith("﻿category,period,spendMinor")
    with tenant_tx(J["tid"]) as s:
        from app.pic.models import AuditEvent
        event = s.execute(select(AuditEvent).where(AuditEvent.object_type == "SPEND_EXPORT", AuditEvent.object_ref == f"cube:{r.headers['X-Content-SHA256'][:12]}")).scalars().first()
        assert event is not None and event.after["rows"] == int(r.headers["X-Row-Count"]) and event.after["filters"]["period_from"] == "2026-08"
    assert spend_analytics._cell("=HYPERLINK(\"http://x\")") == "'=HYPERLINK(\"http://x\")" and spend_analytics._cell("-5") == "-5" and spend_analytics._cell("-cmd") == "'-cmd"
    _problem(client.get("/v1/spend/export?kind=pdf", headers=h), 422)
    assert client.get("/v1/spend/export?kind=lines&supplier=S-UNI", headers=h).status_code == 200


def test_spend2_w12_quality_report_scores_planted_defects_and_keeps_a_history(client, login, env):
    with tenant_tx(J["tid"]) as s:
        base = dict(tenant_id=J["tid"], po_ref=None, supplier_id=J["sup"]["S-BETA"], category="FASTENERS", material_group="FASTENERS", plant="P1", company_code="1000",
                    currency="INR", source="ERP_HISTORY", document_date=date(2026, 7, 1))
        s.add_all([SpendLine(invoice_line_id=uuid.uuid4(), invoice_ref="SP2-DQ-ZERO", period="2026-07", amount_minor=0, **base),
                   SpendLine(invoice_line_id=uuid.uuid4(), invoice_ref="SP2-DQ-OUTLIER", period="2026-07", amount_minor=900_000_000_000_00, **base),
                   SpendLine(invoice_line_id=uuid.uuid4(), invoice_ref="SP2-DQ-FUTURE", period="2027-09", amount_minor=100, **base),
                   SpendLine(invoice_line_id=uuid.uuid4(), invoice_ref="SP2-DQ-GBP", period="2026-07", amount_minor=100, **{**base, "currency": "GBP"}),
                   SpendLine(invoice_line_id=uuid.uuid4(), invoice_ref="SP2-DQ-IC", period="2026-07", amount_minor=100, addressable=True,
                             **{**base, "supplier_id": J["sup"]["S-IC"]})])
        s.add_all([SpendLine(invoice_line_id=uuid.uuid4(), invoice_ref="SP2-DQ-DUP", period="2026-07", amount_minor=777, description="dup", **base) for _ in range(2)])
    h = _h(login, "cm")
    report = client.get("/v1/spend/quality", headers=h).json()
    codes = {c["code"]: c for c in report["checks"]}
    assert report["score"] < 100 and 0 <= report["score"] <= 100 and len(report["checks"]) == 14
    for code in ("NON_POSITIVE_INVOICE_LINES", "AMOUNT_OUTLIER", "FUTURE_PERIOD", "FX_RATE_MISSING", "INTERCOMPANY_ADDRESSABLE", "DUPLICATE_LINES", "NO_LINEAGE"):
        assert codes[code]["count"] >= 1 and codes[code]["status"] in ("WARN", "FAIL"), (code, codes[code])
    assert codes["FEED_STALE"]["status"] in ("WARN", "FAIL"), "lines were just written: the cube has periods waiting for a refresh"
    assert codes["DUPLICATE_LINES"]["samples"][0]["copies"] >= 2 and all(c["remedy"] for c in report["checks"])
    assert round(100 - sum(c["penalty"] for c in report["checks"]), 1) == report["score"]
    run = client.post("/v1/spend/quality/run", headers=h).json()
    assert run["runId"]
    hist = client.get("/v1/spend/quality/history", headers=h).json()["runs"]
    assert hist and hist[0]["score"] == run["score"]
    scoped = client.post("/v1/spend/quality/run", headers=_h(login, "plant2")).json()
    assert "runId" not in scoped and scoped["scope"] == {"plants": ["P2"]}
    with tenant_tx(J["tid"]) as s:
        spend_cube.refresh(s, record_audit=False)
    again = {c["code"]: c for c in client.get("/v1/spend/quality", headers=h).json()["checks"]}
    assert again["CUBE_TIE_OUT"]["status"] == "PASS"


def test_spend2_w13_spend_forecast_picks_a_method_by_backtest_and_reports_its_real_error(client, login, env):
    from app.pic.services import spend_forecast
    flat = [100] * 8
    r = spend_forecast.forecast_series(flat, 3)
    assert r["method"] == "HOLT" and [round(p[0]) for p in r["points"]] == [100, 100, 100] and r["mape"] == 0.0
    seasonal = [100 + 40 * (1 if m % 12 in (2, 3) else 0) for m in range(30)]
    s = spend_forecast.forecast_series(seasonal, 12)
    assert s["method"] in ("SEASONAL", "HOLT_WINTERS") and s["mape"] < 10 and all(low <= mid <= high for mid, low, high in s["points"]) and all(p[1] >= 0 for p in s["points"])
    assert spend_forecast.forecast_series([0, 0, 5, 0, 0, 0, 0, 0], 3) == {}, "fewer than three months with spend: no forecast"
    h = _h(login, "cm")
    snap = client.post("/v1/spend/forecast/snapshot?horizon=3", headers=h)
    assert snap.status_code == 200 and snap.json()["asOf"] == "2026-10" and snap.json()["rows"] >= 3
    again = client.post("/v1/spend/forecast/snapshot?horizon=3", headers=h)
    assert again.json()["rows"] == snap.json()["rows"]
    with tenant_tx(J["tid"]) as sess:   # a forecast issued for August from the July view, judged against what was posted in August
        cat = "FASTENERS"
        actual = sum(l.amount_minor for l in sess.execute(select(SpendLine).where(SpendLine.category == cat, SpendLine.period == "2026-08",
                                                                                   SpendLine.document_type == "INVOICE")).scalars())
        sess.add(spend_forecast.SpendForecastSnapshot(tenant_id=J["tid"], as_of_period="2026-07", category=cat, plant="", period="2026-08", horizon=1, method="HOLT",
                                                      forecast_minor=int(actual * 0.9), low_minor=int(actual * 0.8), high_minor=int(actual * 1.0)))
    acc = client.get("/v1/spend/forecast/accuracy?category=FASTENERS", headers=h).json()
    # one judged forecast is not an accuracy: no figure, and the counts it was built on (T4)
    assert acc["count"] >= 1 and acc["status"] == "INSUFFICIENT_DATA" and acc["mapePct"] is None and acc["bandCoveragePct"] is None and acc["reason"]
    assert acc["minimumJudged"] == spend_forecast.MIN_JUDGED and acc["monthsCount"] == 1 and acc["wapePct"] is not None
    minimums = spend_forecast.MIN_JUDGED, spend_forecast.MIN_MONTHS
    try:
        spend_forecast.MIN_JUDGED, spend_forecast.MIN_MONTHS = 1, 1
        acc = client.get("/v1/spend/forecast/accuracy?category=FASTENERS", headers=h).json()
    finally:
        spend_forecast.MIN_JUDGED, spend_forecast.MIN_MONTHS = minimums
    assert acc["status"] == "OK" and acc["mapePct"] is not None and acc["bandCoveragePct"] is not None and {x["horizon"] for x in acc["byHorizon"]} >= {1}
    fc = client.get("/v1/spend/forecast?horizon=6", headers=h).json()
    for item in fc["series"][:5]:
        assert item["method"] in ("HOLT", "SEASONAL", "HOLT_WINTERS") and item["methodNote"] and "mapePct" in item
        assert all(p["lowMinor"] <= p["forecastMinor"] <= p["highMinor"] for p in item["points"] if "forecastMinor" in p)
    assert client.get("/v1/spend/forecast?horizon=13", headers=h).status_code == 422


def test_spend2_w14_kpis_of_m01_are_registered_and_computed(client, login, env):
    from app.pic.services import kpi
    codes = {"M01.TAIL_SPEND_PCT", "M01.SUPPLIERS_PER_CATEGORY", "M01.SPEND_FORECAST_MAPE", "M01.SAVINGS_PIPELINE", "M01.QUEUE_OVERDUE", "M01.MAVERICK_OVERDUE", "M01.DATA_QUALITY_SCORE"}
    assert codes <= set(kpi.REGISTRY) and all(kpi.REGISTRY[c].compute for c in codes)
    with tenant_tx(J["tid"]) as s:
        items = {i["code"]: i for i in kpi.read(s, "M01", None, None, with_trend=False)}
        assert not [c for c, i in items.items() if "error" in i["detail"]], {c: i["detail"] for c, i in items.items() if "error" in i["detail"]}
        assert items["M01.DATA_QUALITY_SCORE"]["value"] is not None and items["M01.TAIL_SPEND_PCT"]["value"] is not None
        plant = {i["code"]: i for i in kpi.read(s, "M01", None, "P2", with_trend=False)}
        assert Decimal(plant["M01.CONTRACT_COVERAGE"]["denominator"]) < Decimal(items["M01.CONTRACT_COVERAGE"]["denominator"]), "the plant filter now applies to the M01 KPIs"


def test_spend2_w15_taxonomy_maintenance_keeps_history_and_blocks_retiring_a_used_node(client, login, env):
    h, buyer = _h(login, "cm"), _h(login, "buyer")
    new = client.post("/v1/spend/taxonomy", json={"code": "SP2-COMMODITY", "name": "Test commodity", "parent_code": "ALU-DIECAST", "keywords": ["sp2commodityword"]}, headers=h)
    assert new.status_code == 201 and new.json()["level"] == 4
    _problem(client.post("/v1/spend/taxonomy", json={"code": "SP2-COMMODITY", "name": "Again", "parent_code": "ALU-DIECAST"}, headers=h), 409, "NODE_EXISTS")
    _problem(client.post("/v1/spend/taxonomy", json={"code": "SP2-CLASH", "name": "Clash", "parent_code": "ALU-DIECAST", "keywords": ["bolt"]}, headers=h), 409, "KEYWORD_CONFLICT")
    _problem(client.post("/v1/spend/taxonomy", json={"code": "SP2-BAD", "name": "Bad parent", "parent_code": "SP2-COMMODITY"}, headers=h), 422, "INVALID_PARENT")
    _problem(client.post("/v1/spend/taxonomy", json={"code": "SP2-NOPE", "name": "Buyer", "parent_code": "ALU-DIECAST"}, headers=buyer), 403)
    ids = _doc(category="QWERTYKIT", material=False, day=date(2026, 9, 12), qty=1, price=100_00, tag="W15")
    rid, *_ = _review_of(ids["number"])
    assert _decide(client, login, "cm", rid, "SP2-COMMODITY").status_code == 200
    cube = client.get("/v1/spend/analysis?dims=category_l4&category=SP2-COMMODITY", headers=h).json()
    assert [r["category_l4"] for r in cube["rows"]] == ["SP2-COMMODITY"]
    _problem(client.patch("/v1/spend/taxonomy/SP2-COMMODITY", json={"active": False}, headers=h), 409, "NODE_IN_USE")
    assert client.patch("/v1/spend/taxonomy/SP2-COMMODITY", json={"name": "Renamed commodity"}, headers=h).json()["name"] == "Renamed commodity"
    tax = client.get("/v1/spend/taxonomy", headers=h).json()
    assert next(n for n in tax if n["code"] == "SP2-COMMODITY")["lines"] >= 1


def test_spend2_s16_concurrent_decisions_on_one_review_or_hit_are_serialised(client, login, env):
    """S16: two stewards (or two owners) deciding the same item at the same moment both read OPEN and the last write won silently."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    ids = _doc(category="CONCURRENTITEM", material=False, day=date(2026, 9, 14), qty=1, price=500_00, tag="S16")
    rid, *_ = _review_of(ids["number"])
    barrier = threading.Barrier(2)

    def decide(who, category):
        with tenant_tx(J["tid"]) as s:
            s.info["principal"] = _principal(s, who)
            review = s.get(spend.ClassificationReview, uuid.UUID(rid))
            barrier.wait(timeout=20)
            try:
                spend.decide_review(s, review, category, "concurrent")
                return ("ok", category)
            except Problem as exc:
                return (exc.code, category)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda args: decide(*args), (("cm", "FASTENERS"), ("cm2", "RUBBER-SEALS"))))
    assert sorted(r[0] for r in results) == ["ILLEGAL_TRANSITION", "ok"], results
    winner = next(c for code, c in results if code == "ok")
    assert {r[4] for r in _lines(ids["number"])} == {winner}
    hit_doc = _doc(day=date(2026, 9, 14), qty=10, price=1000_00, received=0, tag="S16B")
    with tenant_tx(J["tid"]) as s:
        hit_id = s.execute(select(MaverickHit.id).where(MaverickHit.invoice_ref == hit_doc["number"])).scalar_one()
    barrier2 = threading.Barrier(2)

    def dispose(who, disposition):
        with tenant_tx(J["tid"]) as s:
            s.info["principal"] = _principal(s, who)
            hit = s.get(MaverickHit, hit_id)
            barrier2.wait(timeout=20)
            try:
                spend.dispose(s, hit, disposition, "concurrent disposition", reason_code="OTHER")
                return "ok"
            except Problem as exc:
                return exc.code

    with ThreadPoolExecutor(2) as pool:
        out = list(pool.map(lambda args: dispose(*args), (("fin", "ACCEPTED_EXCEPTION"), ("ph", "POLICY_BREACH"))))
    assert sorted(out) == ["ILLEGAL_TRANSITION", "ok"], out


def test_spend2_s17_buyer_is_a_dimension_and_a_filter_and_freshness_counts_waiting_documents(client, login, env):
    ids = _doc(day=date(2026, 9, 20), qty=3, price=2000_00, tag="S17")
    h = _h(login, "cm")
    cube = client.get("/v1/spend/analysis?dims=buyer&period_from=2026-09&period_to=2026-09", headers=h).json()
    mine = next(r for r in cube["rows"] if r["buyer"] == _email("buyer"))
    assert mine["spendMinor"] >= 6_000_00 and mine["buyerName"] == "Bala Buyer"
    only = client.get(f"/v1/spend/analysis?dims=supplier&buyer={_email('buyer')}&period_from=2026-09&period_to=2026-09", headers=h).json()
    assert only["totalMinor"] == mine["spendMinor"] and only["filters"]["buyers"] == [_email("buyer")]
    assert client.get("/v1/spend/analysis?dims=buyer&buyer=nobody@nowhere.example", headers=h).json()["rows"] == []
    # a document waiting in the outbox is visible as one the cube does not know yet (nothing is committed: the transaction is rolled back)
    class Rollback(Exception):
        pass
    try:
        with tenant_tx(J["tid"]) as sess:
            outbox.emit(sess, "debit_note.posted", "DEBIT_NOTE", uuid.uuid4(), "SP2-WAITING", {"invoice": "SP2-WAITING", "erpDocument": "ERP-SP2-WAITING", "grossMinor": 1})
            waiting = spend_cube.freshness(sess)
            assert waiting["pendingEvents"] >= 1 and waiting["feedBehind"] is True
            raise Rollback()
    except Rollback:
        pass
    assert client.get("/v1/spend/cube-status", headers=h).json()["cube"]["pendingEvents"] == 0
    assert ids["number"]


def test_spend2_s18_a_stale_fx_rate_is_a_data_quality_finding(client, login, env):
    before = next(c for c in client.get("/v1/spend/quality", headers=_h(login, "cm")).json()["checks"] if c["code"] == "FX_RATE_STALE")["count"]
    with tenant_tx(J["tid"]) as s:
        s.add(SpendLine(tenant_id=J["tid"], invoice_line_id=uuid.uuid4(), invoice_ref="SP2-STALE-FX", po_ref="P", supplier_id=J["sup"]["S-BETA"], category="FASTENERS",
                        material_group="FASTENERS", plant="P1", company_code="1000", period="2026-09", amount_minor=100_00, currency="USD", fx_rate=Decimal("80.0"),
                        fx_date=date(2026, 3, 30), amount_group_minor=8_000_00, document_date=date(2026, 9, 10), source="ERP_HISTORY"))
    report = client.get("/v1/spend/quality", headers=_h(login, "cm")).json()
    stale = next(c for c in report["checks"] if c["code"] == "FX_RATE_STALE")
    assert stale["count"] == before + 1 and stale["status"] in ("WARN", "FAIL"), "a rate of 30 March on a 10 September document is flagged"


def test_spend2_w16_the_export_is_capped_by_the_tenant_rule_and_says_so(client, login, env):
    kit.rule_version(J["sc"], "SPEND-GOVERNANCE", "2026.9-SP2-CAP", date(2026, 11, 1), {"exportMaxRows": 3}, "export cap for the test")
    h = _h(login, "cm")
    cube = client.get("/v1/spend/export?kind=cube&dims=period,category", headers=h)
    lines = client.get("/v1/spend/export?kind=lines", headers=h)
    assert cube.status_code == lines.status_code == 200
    assert cube.headers["X-Truncated"] == "true" and int(cube.headers["X-Row-Count"]) == 3
    assert lines.headers["X-Truncated"] == "true" and int(lines.headers["X-Row-Count"]) == 3 and len(lines.text.strip().splitlines()) == 4


def test_spend2_s19_leakage_is_in_the_group_currency_and_the_kpi_by_plant_is_scoped(client, login, env):
    """S19: the compliance leakage added price variances of every document currency as if they were rupees."""
    ids = _doc(supplier="S-BETA", day=date(2026, 10, 12), qty=10, price=1000_00, currency="USD", deviation=True, tag="S19")
    lines = _lines(ids["number"])
    variance_usd = lines[0][7]
    assert "OFF_CONTRACT_PRICE" in lines[0][5] and variance_usd == 10 * (1000_00 - 900_00)      # 10 units, USD 1,000 against the standard price 900
    with tenant_tx(J["tid"]) as sess:
        spend_cube.refresh(sess, record_audit=False)
        report = spend.compliance(sess)
    assert report["currency"] == "INR" and report["leakageMinor"] >= variance_usd * 85, "converted at the rate valid on the invoice date (85.00 from 1 October)"
    assert report["leakageMinor"] < variance_usd * 85 * 50


def test_spend2_s20_huge_values_unicode_names_and_a_one_line_cube(client, login, env):
    """S20: a line of 10^18 minor units, summed into the BIGINT cube, would have stopped the refresh for the whole tenant."""
    from sqlalchemy.exc import IntegrityError
    base = dict(tenant_id=J["tid"], supplier_id=J["sup"]["S-UNI"], category="FASTENERS", material_group="FASTENERS", plant="P1", company_code="1000", currency="INR",
                period="2026-09", po_ref="P", source="ERP_HISTORY", document_date=date(2026, 9, 3))
    with pytest.raises(IntegrityError):
        with tenant_tx(J["tid"]) as s:
            s.add(SpendLine(invoice_line_id=uuid.uuid4(), invoice_ref="SP2-HUGE", amount_minor=10 ** 18, **base))
    with pytest.raises(IntegrityError):
        with tenant_tx(J["tid"]) as s:
            s.add(SpendLine(invoice_line_id=uuid.uuid4(), invoice_ref="SP2-HUGE-NEG", amount_minor=-(10 ** 16), **base))
    with tenant_tx(J["tid"]) as s:       # the largest accepted value still aggregates
        s.add(SpendLine(invoice_line_id=uuid.uuid4(), invoice_ref="SP2-BIG", amount_minor=10 ** 15, **base))
        s.add(SpendLine(invoice_line_id=uuid.uuid4(), invoice_ref="SP2-BIG2", amount_minor=10 ** 15, **base))
    h = _h(login, "cm")
    r = client.get("/v1/spend/analysis?dims=supplier&supplier=S-UNI&period_from=2026-09&period_to=2026-09", headers=h).json()
    assert r["rows"][0]["name"] == "Zażółć Gęślą Jaźń Spółka" and r["rows"][0]["spendMinor"] >= 2 * 10 ** 15
    exported = client.get("/v1/spend/export?kind=cube&dims=supplier&supplier=S-UNI&period_from=2026-09&period_to=2026-09", headers=h)
    assert exported.status_code == 200 and "S-UNI" in exported.text


# ---------------------------------------------------------------- the lead's second round (T1-T5)
def test_spend2_t1_a_tenant_admin_sees_the_maverick_work_but_cannot_decide_it(client, login, env):
    """T1: the admin opens the maverick tab (work list, rules, cube status) and runs its admin actions; reading the spend data and deciding stay with
    spend:read, which the admin role does not hold (separation of duties)."""
    admin, buyer = _h(login, "admin"), _h(login, "buyer")
    hit_doc = _doc(day=date(2026, 9, 21), qty=10, price=1000_00, received=0, tag="T1")
    with tenant_tx(J["tid"]) as s:
        hit_id = s.execute(select(MaverickHit.id).where(MaverickHit.invoice_ref == hit_doc["number"])).scalar_one()
    assert client.get("/v1/spend/maverick/worklist?status=OPEN", headers=admin).status_code == 200
    rules = client.get("/v1/spend/maverick-rules", headers=admin)
    assert rules.status_code == 200 and len(rules.json()["rules"]) >= 9
    assert client.get("/v1/spend/cube-status", headers=admin).status_code == 200
    assert client.post("/v1/spend/maverick/escalate", headers=admin).status_code == 200
    assert client.post("/v1/admin/spend/refresh", json={}, headers=admin).status_code == 200
    for path in ("/v1/spend/overview", "/v1/spend/classification-queue", "/v1/spend/maverick/repeat-offenders", "/v1/spend/quality"):
        _problem(client.get(path, headers=admin), 403)
    _problem(client.post(f"/v1/spend/maverick-hits/{hit_id}/disposition", json={"disposition": "POLICY_BREACH", "comment": "admin tries to decide"}, headers=admin), 403)
    _problem(client.post(f"/v1/spend/maverick-hits/{hit_id}/resolve", json={"recovered_minor": 1, "note": "admin tries to close"}, headers=admin), 403)
    for path in ("/v1/spend/maverick/worklist", "/v1/spend/maverick-rules", "/v1/spend/cube-status"):
        _problem(client.get(path, headers=buyer), 403)     # a buyer holds neither the spend scope nor an admin one


def test_spend2_t2_a_read_never_waits_for_or_races_with_a_refresh(client, login, env):
    """T2: GET /v1/spend/duplicates (and every cube read) refreshed dirty periods itself, loaded the refresh-state row, waited for the refresh lock of
    another request and then updated its stale copy: a 412 STALE_WRITE on a read. A read now takes the lock only if it is free and otherwise serves the
    data as it is; a refresh that is asked for waits and works on the state as it is then."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    h = _h(login, "steward")
    _doc(day=date(2026, 9, 25), qty=2, price=300_00, tag="T2A")
    key = {"k": f"spendview:{J['tid']}"}
    with tenant_tx(J["tid"]) as holder:     # a refresh is running elsewhere (it holds the lock for its whole transaction)
        holder.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), key)
        with ThreadPoolExecutor(2) as pool:
            r1 = pool.submit(client.get, "/v1/spend/duplicates", headers=h).result(timeout=120)
            r2 = pool.submit(client.get, "/v1/spend/cube-status", headers=_h(login, "cm")).result(timeout=120)
        assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
        assert r2.json()["cube"]["stale"] is True and r2.json()["cube"]["dirtyPeriods"], "the read served the cube as it was and says which periods wait"
    assert client.get("/v1/spend/duplicates", headers=h).status_code == 200
    assert client.get("/v1/spend/cube-status", headers=_h(login, "cm")).json()["cube"]["dirtyPeriods"] == []
    # several readers and refreshers at the same moment, each having loaded the state row before the others committed: none fails
    for round_ in range(2):
        _doc(day=date(2026, 9, 26), qty=2, price=300_00, tag=f"T2B{round_}")
        workers = 6
        barrier = threading.Barrier(workers)

        def work(n):
            with tenant_tx(J["tid"]) as s:
                s.info["principal"] = _principal(s, "cm")
                spend_cube._state(s, "spend_cube_summary")          # the copy a stale write would use
                barrier.wait(timeout=30)
                if n % 3 == 0:
                    return spend_cube.refresh_spend_views(J["tid"], dirty_only=True, session=s)["cube"]["mode"]
                return spend_cube.ensure_fresh(s)["stale"]

        with ThreadPoolExecutor(workers) as pool:
            outcomes = list(pool.map(work, range(workers)))
        assert len(outcomes) == workers
    with tenant_tx(J["tid"]) as s:
        assert spend_cube.freshness(s)["dirtyPeriods"] == []


def test_spend2_t3_the_duplicate_scan_finds_every_pair_of_the_full_comparison(client, login, env):
    """T3: the name comparison skips pairs whose length / letter counts cannot reach the threshold before the (slow) full ratio; no pair may be lost."""
    from app.pic.services import spend_workflow as w
    with tenant_tx(J["tid"]) as s:
        s.info["principal"] = None
        suppliers = list(s.execute(select(Supplier)).scalars())
        suppliers.sort(key=lambda x: x.code)
        clusters = w.find_clusters(s)
    in_cluster = {}
    for c in clusters:
        for m in c["suppliers"]:
            in_cluster[m.code] = c["key"]
    items = sorted(((x, w.norm_name(x.legal_name)) for x in suppliers), key=lambda x: (x[1], x[0].code))
    expected = [(a.code, b.code) for i, (a, na) in enumerate(items) for b, nb in items[i + 1:i + 26] if w._name_similarity(na, nb) >= w.NAME_THRESHOLD]
    assert expected, "the fixtures hold similar names"
    assert all(in_cluster.get(x) is not None and in_cluster.get(x) == in_cluster.get(y) for x, y in expected)


def test_spend2_t4_the_forecast_error_kpi_says_when_there_is_too_little_history(client, login, env):
    """T4: a MAPE over a handful of forecasts (here one) is not reported as a number; the KPI carries the reason and the counts."""
    from app.pic.services import kpi
    with tenant_tx(J["tid"]) as s:
        item = {i["code"]: i for i in kpi.read(s, "M01", None, None, with_trend=False)}["M01.SPEND_FORECAST_MAPE"]
    assert item["value"] is None and item["detail"]["status"] == "INSUFFICIENT_DATA" and "Not enough forecast history" in item["detail"]["reason"]
    assert item["detail"]["minimumJudged"] == spend_forecast.MIN_JUDGED and item["detail"]["judged"] < spend_forecast.MIN_JUDGED
    assert {"series", "months", "minimumMonths", "judged"} <= set(item["detail"])
    ok = spend_forecast._accuracy_result(40, 5, 6, 12.5, -1.0, 78.0, 9.0, [], [], "2026-10")
    assert ok["status"] == "OK" and ok["mapePct"] == 12.5 and ok["reason"] is None
    thin = spend_forecast._accuracy_result(40, 5, 2, 755.7, 1.0, 50.0, 9.0, [], [], "2026-10")
    assert thin["status"] == "INSUFFICIENT_DATA" and thin["mapePct"] is None and "2 of 3 months" in thin["reason"] and thin["wapePct"] == 9.0
