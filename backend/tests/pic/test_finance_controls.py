"""Finance controls that need no HTTP round trip: OCR-variant invoice numbers, TDS thresholds / no-PAN rate / catch-up, the MSME interest formula.

``compute_tds`` is exercised against a scripted session (the rule set is the documented default), so each threshold case is one line.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.pic.platform import finance_defaults
from app.pic.platform.errors import Problem
from app.pic.services import finance_controls as fc


@pytest.mark.parametrize("a,b", [
    ("INV-0012", "inv 12"), ("INV/0012", "INV12"), ("INVO12", "INV-012"), ("KD/FK-REV-03", "KD FK REV 3"), ("A-1I", "a 11"),
])
def test_ocr_and_formatting_variants_share_a_key(a, b):
    assert fc.normalise_invoice_no(a) == fc.normalise_invoice_no(b)


@pytest.mark.parametrize("a,b", [("INV-0012", "INV-0021"), ("KD/FK-REV-03", "KD/FK-REV-03B"), ("INV-10", "INV-100"), ("AB-1", "BA-1")])
def test_different_numbers_stay_different(a, b):
    assert fc.normalise_invoice_no(a) != fc.normalise_invoice_no(b)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: [])

    def scalar(self):
        return self.rows

    def one(self):
        return self.rows


class _Session:
    """Answers the three queries compute_tds makes: the rule set (none -> defaults), credit notes, earlier invoices of the supplier."""

    def __init__(self, prior_total=0, prior_taxed=0, credit=0):
        self.prior, self.credit = (prior_total, prior_taxed), credit

    def execute(self, statement):
        text = str(statement)
        if "rule_set" in text:
            return _Result([])
        if "credit_note" in text:
            return _Result(self.credit)
        if "debit_note" in text:  # earlier debit notes of the section: none
            return _Result((0, 0))
        return _Result(self.prior)


def _invoice(net_minor, **kw):
    return SimpleNamespace(id="i", tds_section=None, withholding_tax_minor=0, company_code="1000", net_minor=net_minor, fiscal_year="2026-27", **kw)


def _supplier(section, pan=True):
    return SimpleNamespace(id="s", code="S1", tds_section=section, pan_hash="x" if pan else None)


def test_no_section_no_tds_and_migrated_withholding_is_kept():
    assert fc.compute_tds(_Session(), _invoice(10_000_000), _supplier(None)) == {}
    migrated = _invoice(10_000_000)
    migrated.withholding_tax_minor = 5_000
    assert fc.compute_tds(_Session(), migrated, _supplier("194C-OTH")) == {}


def test_unknown_section_blocks_posting():
    with pytest.raises(Problem) as err:
        fc.compute_tds(_Session(), _invoice(10_000_000), _supplier("999Z"))
    assert err.value.code == "TDS_SECTION_UNKNOWN"


def test_below_both_thresholds_nothing_is_withheld():
    tds = fc.compute_tds(_Session(), _invoice(2_000_000), _supplier("194C-OTH"))   # INR 20,000 < single 30,000 and annual 1,00,000
    assert tds["tdsMinor"] == 0 and tds["taxableMinor"] == 0 and tds["ratePct"] == Decimal(2)


def test_single_payment_above_threshold_is_taxed_in_full():
    tds = fc.compute_tds(_Session(), _invoice(5_000_000), _supplier("194C-OTH"))   # INR 50,000 > single 30,000
    assert tds["taxableMinor"] == 5_000_000 and tds["tdsMinor"] == 100_000


def test_crossing_the_annual_threshold_catches_up_earlier_untaxed_payments():
    # 90,000 invoiced earlier (nothing taxed: each below 30,000); this 20,000 takes the year to 1,10,000 > 1,00,000 -> TDS on all 1,10,000
    tds = fc.compute_tds(_Session(prior_total=9_000_000, prior_taxed=0), _invoice(2_000_000), _supplier("194C-OTH"))
    assert tds["taxableMinor"] == 11_000_000 and tds["tdsMinor"] == 220_000
    # the next payment only adds its own base: the earlier ones are already taxed
    nxt = fc.compute_tds(_Session(prior_total=11_000_000, prior_taxed=11_000_000), _invoice(1_000_000), _supplier("194C-OTH"))
    assert nxt["taxableMinor"] == 1_000_000 and nxt["tdsMinor"] == 20_000


def test_credit_notes_reduce_the_base():
    tds = fc.compute_tds(_Session(credit=1_000_000), _invoice(5_000_000), _supplier("194C-OTH"))
    assert tds["baseMinor"] == 4_000_000 and tds["tdsMinor"] == 80_000


def test_missing_pan_uses_the_higher_rate():
    tds = fc.compute_tds(_Session(), _invoice(5_000_000), _supplier("194C-OTH", pan=False))
    assert tds["ratePct"] == Decimal(20) and tds["tdsMinor"] == 1_000_000 and tds["noPan"] is True


def test_purchase_of_goods_is_taxed_only_above_the_limit():
    sec = _supplier("194Q")
    assert fc.compute_tds(_Session(prior_total=400_000_000), _invoice(50_000_000), sec)["tdsMinor"] == 0            # 4.5 Cr < 5 Cr... in paise: below limit
    over = fc.compute_tds(_Session(prior_total=480_000_000), _invoice(50_000_000), sec)                            # 5.3 Cr: 30 lakh above the limit
    assert over["taxableMinor"] == 30_000_000 and over["tdsMinor"] == 30_000


def test_msme_interest_needs_a_published_bank_rate(monkeypatch):
    monkeypatch.setattr(fc, "rule_body", lambda session, key, default, **scope: default)
    assert fc.msme_interest_minor(None, 1_000_000, date(2027, 1, 1), date(2027, 2, 1)) is None
    monkeypatch.setattr(fc, "rule_body", lambda session, key, default, **scope: {**default, "bankRatePct": 6})
    assert fc.msme_interest_minor(None, 1_000_000, date(2027, 1, 1), date(2027, 1, 1)) == 0
    # 3 x 6 % = 18 % a year, compounded monthly: 1.5 % a month; 60 days overdue = two months -> 1.5 % twice
    assert fc.msme_interest_minor(None, 1_000_000, date(2027, 1, 1), date(2027, 3, 2)) == round(1_000_000 * (1.015 ** 2 - 1))


def test_defaults_are_the_seeded_rule_sets():
    assert fc.MSME_DEFAULT is finance_defaults.MSME_DEFAULT and fc.TDS_DEFAULT is finance_defaults.TDS_DEFAULT
    assert fc.MSME_DEFAULT["maxDays"] == 45 and set(fc.TDS_DEFAULT["sections"]) >= {"194C-IND", "194C-OTH", "194J-PRO", "194Q"}


# ---------------------------------------------------------------- Form 26Q quarters, CSV safety
def test_quarters_follow_the_indian_fiscal_year():
    assert fc.quarter_range("2026-27", "Q1") == (date(2026, 4, 1), date(2026, 6, 30))
    assert fc.quarter_range("2026-27", "Q3") == (date(2026, 10, 1), date(2026, 12, 31))
    assert fc.quarter_range("2026-27", "Q4") == (date(2027, 1, 1), date(2027, 3, 31))
    with pytest.raises(Problem):
        fc.quarter_range("2026", "Q1")
    with pytest.raises(Problem):
        fc.quarter_range("2026-27", "Q5")


def test_csv_cells_that_look_like_formulas_are_quoted():
    assert fc._safe("=HYPERLINK(1)") == "'=HYPERLINK(1)" and fc._safe("@cmd") == "'@cmd" and fc._safe("-5") == "-5" and fc._safe("PAY-1") == "PAY-1"


def test_note_tds_follows_the_payment_rate():
    note = SimpleNamespace(tds_base_minor=1_000_000)
    assert fc.note_tds_at_payment(note, Decimal("2")) == 20_000 and fc.note_tds_at_payment(note, Decimal("0.5")) == 5_000
    assert fc.note_tds_at_payment(SimpleNamespace(tds_base_minor=0), Decimal("2")) == 0 and fc.note_tds_at_payment(note, None) == 0


# ---------------------------------------------------------------- bank statement parsing (camt.053, MT940)
from pathlib import Path  # noqa: E402

from app.pic.services import bank_statement as bs  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "bank"
FILL = {"{{STMT}}": "STMT-1", "{{PAY_OK}}": "PAY-880001", "{{PAY_RET}}": "PAY-880002", "{{AMT_OK}}": "236000.00", "{{AMT_RET}}": "118000.00",
        "{{AMT_OK_MT}}": "236000,00", "{{AMT_RET_MT}}": "118000,00"}


def _fixture(name: str) -> str:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    for key, value in FILL.items():
        text = text.replace(key, value)
    return text


def test_camt053_entries_credited_returned_and_foreign():
    st = bs.parse(_fixture("camt053_sample.xml").encode())
    assert st["format"] == "CAMT053" and st["statementId"] == "STMT-1" and st["account"] == "50200011223344" and len(st["entries"]) == 3
    paid, back, other = st["entries"]
    assert paid["direction"] == "D" and not paid["returned"] and paid["amountMinor"] == 23_600_000 and paid["bankRef"] == "HDFCR52027010500123"
    assert "PAY-880001" in paid["text"]
    assert back["returned"] and back["amountMinor"] == 11_800_000 and "AC04" in back["reason"] and "Beneficiary account closed" in back["reason"]
    assert other["direction"] == "C" and not other["returned"]


def test_mt940_entries_credited_returned_and_foreign():
    st = bs.parse(_fixture("mt940_sample.sta").encode())
    assert st["format"] == "MT940" and st["statementId"] == "STMT-1-00001.001" and st["account"] == "50200011223344" and len(st["entries"]) == 3
    paid, back, other = st["entries"]
    assert not paid["returned"] and paid["amountMinor"] == 23_600_000 and paid["bankRef"] == "HDFCR52027010500123" and "PAY-880001" in paid["text"]
    assert back["returned"] and back["amountMinor"] == 11_800_000 and "BENEFICIARY ACCOUNT CLOSED" in back["reason"] and back["valueDate"] == "2027-01-07"
    assert other["direction"] == "C" and "NONREF" in other["text"]


@pytest.mark.parametrize("data,why", [
    (b"<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'b'>]><Document/>", "DTD"),
    (b"<Document><Other/></Document>", "Stmt"),
    (b"<Document><unclosed>", "cannot be read"),
    (b":25:123\n:61:2701050105D1,00NTRFX//Y\n", "transaction reference"),
    (b":20:REF\n:61:garbage\n", "cannot be read"),
])
def test_unreadable_statements_are_refused_with_a_problem(data, why):
    with pytest.raises(Problem) as err:
        bs.parse(data)
    assert err.value.status == 422 and why in err.value.detail


def test_oversized_statement_is_refused():
    with pytest.raises(Problem) as err:
        bs.parse(b"x" * (bs.MAX_BYTES + 1))
    assert err.value.status == 413
