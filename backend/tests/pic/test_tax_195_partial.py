"""Section 195 TDS for non-residents, partial payments and the Form 16A information copy (engineer C, 9 November 2026).

Part 1 tests the rate determination as a pure function of the rule body (treaty against Act rate, surcharge and cess, no PAN with and without the
non-resident relief, gross-up arithmetic, certificate) and the PDF writer. Part 2 runs the whole flow in tenant AXN with its own MOCK vendors and
orders (codes T195*, business dates January 2028, quarter Q4 of 2027-28, so nothing of the signature case or of pack tax_nonresident is touched):
posting with the s.195 determination, the Form 15CA / 15CB checkpoint (409), DTAA / Act / gross-up payments, partial payments with TDS deducted once,
a returned partial, SoD, MSME due dates, early payment, ERP messages, bank files, the 26Q / 27Q returns and the 16A PDF endpoint.
"""
import copy
import re
import uuid
from urllib.parse import quote
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (AppUser, AuditEvent, IntegrationMessage, Invoice, Payment, PurchaseOrder, RemittanceCertificate, RuleSet, Supplier,
                            SupplierTaxResidency, Tenant)
from app.pic.platform import clock, finance_defaults
from app.pic.platform.auth import hash_password
from app.pic.platform.errors import Problem
from app.pic.seed.axion import Scenario, at
from app.pic.seed.datasets import tax_nonresident as kit195
from app.pic.services import early_payment, form16a_pdf, nonresident_tax, payables, settlement, tds_returns

from .conftest import PASSWORD

RULE = finance_defaults.TDS_195_DEFAULT
ALL_DOCS = {"TRC", "FORM_10F", "NO_PE", "TAX_ID", "ADDRESS", "PAN"}
L = 100_000 * 100


def det(**kw):
    base = {"nature": "FTS", "country": "DE", "payee_type": "COMPANY", "docs": set(ALL_DOCS), "base_inr_minor": 10 * L}
    base.update(kw)
    return nonresident_tax.determine(RULE, **base)


# ================================================================ part 1: determination (pure)
def test_treaty_rate_wins_over_act_rate_with_trc_and_10f():
    d = det()
    assert d["basis"] == "DTAA" and d["ratePct"] == "10.0000" and d["treaty"]["article"] == "12"
    assert d["actEffectivePct"] == "20.8000" and d["surchargePct"] == "0" and d["cessPct"] == "4"   # 20 % + 4 % cess, no surcharge below 1 crore
    assert d["taxInrMinor"] == 1 * L and d["sectionLabel"] == "195" and d["mock"] is True and d["returnForm"] == "27Q"


@pytest.mark.parametrize("missing", ["TRC", "FORM_10F"])
def test_expired_trc_or_10f_falls_back_to_act_rate(missing):
    d = det(nature="ROYALTY", country="US", docs=ALL_DOCS - {missing}, why={missing: f"{missing} expired on 2027-03-31"})
    assert d["basis"] == "ACT" and d["ratePct"] == "20.8000" and d["treaty"] is None
    assert "expired" in d["treatyUnavailable"]


def test_no_treaty_article_or_no_treaty_uses_the_act():
    uae = det(country="AE")          # the MOCK India-UAE entry has no fees-for-technical-services article
    assert uae["basis"] == "ACT" and "no article for FTS" in uae["treatyUnavailable"]
    france = det(country="FR")
    assert france["basis"] == "ACT" and "no treaty" in france["treatyUnavailable"]


def test_treaty_entry_that_needs_a_no_pe_declaration():
    assert det(nature="OTHER", docs=ALL_DOCS)["ratePct"] == "0.0000"
    without = det(nature="OTHER", docs=ALL_DOCS - {"NO_PE"})
    assert without["basis"] == "ACT" and without["ratePct"] == "36.4000"     # foreign company: 35 % + 4 % cess


def test_surcharge_slabs_and_cess():
    assert det(country="FR", base_inr_minor=2 * 100 * L)["ratePct"] == "21.2160"        # above 1 crore: 2 % surcharge
    assert det(country="FR", base_inr_minor=11 * 100 * L)["ratePct"] == "21.8400"       # above 10 crore: 5 %
    individual = det(country="FR", payee_type="NON_COMPANY", base_inr_minor=60 * L)      # non-company above 50 lakh: 10 %
    assert individual["ratePct"] == "22.8800" and individual["surchargePct"] == "10"


def test_no_pan_206aa_and_the_non_resident_relief():
    no_pan = det(country="SG", docs=ALL_DOCS - {"PAN", "TAX_ID"}, why={"TAX_ID": "no tax identification number"})
    assert no_pan["basis"] == "NO_PAN_206AA" and no_pan["ratePct"] == "20.8000" and no_pan["noPanSection"] == "206AA"
    assert no_pan["noPanReliefMissing"] == ["no tax identification number"]
    relief = det(country="SG", docs=ALL_DOCS - {"PAN"})                                   # TRC, tax id, address: Rule 37BC relief
    assert relief["basis"] == "DTAA" and relief["ratePct"] == "10.0000" and relief["noPanRelief"] is True
    other = det(nature="OTHER", payee_type="NON_COMPANY", country="FR", docs=ALL_DOCS - {"PAN"})   # OTHER is not in the relief list
    assert other["basis"] == "NO_PAN_206AA" and other["ratePct"] == "31.2000"            # max(20 %, 30 % + cess)
    body = copy.deepcopy(RULE)
    body["noPan"]["ratePct"] = 25
    assert nonresident_tax.determine(body, nature="FTS", country="SG", payee_type="COMPANY", docs=ALL_DOCS - {"PAN", "TAX_ID"},
                                     base_inr_minor=10 * L)["ratePct"] == "25.0000"


def test_gross_up_arithmetic():
    d = det(country="AE", base_inr_minor=80_000_00, gross_up=True)
    assert d["ratePct"] == "20.8000" and d["grossUp"] is True
    assert d["taxableInrMinor"] == 101_010_10                       # 80,000 / (1 - 0.208)
    assert d["taxInrMinor"] == 21_010_00                             # 21,010.10 rounded to the rupee (rule roundInrToMinor)
    assert abs(d["taxableInrMinor"] * Decimal("0.208") - d["taxInrMinor"]) < 100
    # the grossed-up amount crosses the 1-crore surcharge slab: the rate is the slab's
    crossing = det(country="FR", base_inr_minor=90 * L, gross_up=True)
    assert crossing["surchargePct"] == "2" and crossing["ratePct"] == "21.2160" and crossing["taxableInrMinor"] > 100 * L


def test_certificate_rate_and_rule_switches():
    assert det(certificate_rate=Decimal("2"))["basis"] == "LOWER_DEDUCTION_CERTIFICATE"
    body = copy.deepcopy(RULE)
    body["treatyRateInclusive"] = False
    assert nonresident_tax.determine(body, nature="FTS", country="DE", payee_type="COMPANY", docs=ALL_DOCS, base_inr_minor=10 * L)["ratePct"] == "10.4000"
    with pytest.raises(Problem) as exc:
        det(nature="DIVIDEND")
    assert exc.value.code == "TDS_195_NATURE_UNKNOWN"
    assert nonresident_tax.return_form("195-FTS") == "27Q" and nonresident_tax.return_form("194J-TECH") == "26Q"
    assert nonresident_tax.section_labels(RULE)["195-ROYALTY"]["label"] == "195 - Royalty"


# ================================================================ part 1: PDF writer
def _cert(payments: int = 2, form: str = "26Q") -> dict:
    return {"form": "16A", "financialYear": "2027-28", "assessmentYear": "2028-29", "quarter": "Q4", "periodFrom": "2028-01-01", "periodTo": "2028-03-31",
            "companyCode": "1000", "certificateNo": None, "returnForm": form,
            "deductor": {"tan": "CHEA99999Z", "pan": "AAACA9999Z", "name": "Axion (Test)", "address": "Hosur"},
            "deductee": {"supplier": "T1", "name": "Deductee (Test) Pvt Ltd", "pan": "AAKCK4821P", "residency": "RESIDENT", "country": "IN", "address": {}},
            "section": "194J-TECH", "sectionLabel": "Technical services",
            "payments": [{"payment": f"PAY-{n}", "invoice": f"INV-{n}", "dateOfPaymentCredit": "2028-01-10", "amountPaidCreditedMinor": 12_34_567_00,
                          "ratePct": "2.000", "taxDeductedMinor": 24_691_34, "dateOfDeduction": "2028-01-10", "certificate197": None} for n in range(payments)],
            "totals": {"amountPaidCreditedMinor": 1, "taxDeductedMinor": 2, "taxDepositedMinor": 3},
            "challans": [{"bsrCode": "0510308", "challanSerialNo": "00042", "depositDate": "2028-02-07", "challanAmountMinor": 400_000}],
            "depositAllocation": "PRO_RATA_BY_TAX_DEDUCTED", "missingMandatory": []}


def _check_xref(pdf: bytes) -> int:
    start = int(re.search(rb"startxref\n(\d+)\n%%EOF", pdf).group(1))
    assert pdf[start:start + 4] == b"xref"
    count = int(re.search(rb"xref\n0 (\d+)\n", pdf[start:]).group(1))
    offsets = [int(x) for x in re.findall(rb"(\d{10}) 00000 n ", pdf[start:])]
    assert len(offsets) == count - 1
    for number, offset in enumerate(offsets, start=1):
        assert pdf[offset:].startswith(b"%d 0 obj" % number)
    return len(re.findall(rb"/Type /Page /Parent", pdf))


def test_pdf_information_copy_content_and_structure():
    pdf = form16a_pdf.render([_cert()])
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    assert b"Information copy \x97 the statutory Form 16A must be downloaded from TRACES" in pdf     # banner, em dash in WinAnsi
    assert b"(INFORMATION COPY) Tj" in pdf                                                          # diagonal watermark
    assert b"AAKCK4821P" in pdf and b"CHEA99999Z" in pdf and b"12,34,567.00" in pdf and b"24,691.34" in pdf and b"0510308" in pdf
    assert b"Form 26Q" in pdf and b"2028-29" in pdf and b"Deductee \\(Test\\) Pvt Ltd" in pdf     # parentheses escaped
    assert _check_xref(pdf) == 1


def test_pdf_paginates_and_marks_every_page():
    pdf = form16a_pdf.render([_cert(payments=90), _cert(payments=1, form="27Q")])
    pages = _check_xref(pdf)
    assert pages >= 4
    assert pdf.count(b"(INFORMATION COPY) Tj") == pages and pdf.count(b"Page 1 of %d" % pages) == 1
    assert b"payments to non-residents" in pdf
    assert form16a_pdf.inr(123_456_789_00) == "12,34,56,789.00" and form16a_pdf.inr(-5) == "-0.05" and form16a_pdf.inr(None) == ""


# ================================================================ part 2: the flow in AXN
DAY0, POST_DAY, RUN1, RUN2, RUN3, RETURN_DAY = date(2028, 1, 3), date(2028, 1, 6), date(2028, 1, 10), date(2028, 1, 17), date(2028, 1, 24), date(2028, 1, 19)
FY, Q = "2027-28", "Q4"
V = {
    "DE": kit195.Vendor("T195DE", "Testwerk Engineering GmbH (fictional test)", "DE", "EUR", "N30",
                        {"line1": "Teststrasse 1", "city": "Koeln", "country": "DE"},
                        {"account": "DE00TEST000000000001", "swift": "TESTDEFFXXX", "bearer": "SHAR", "purpose": "S1007"},
                        {"residency": "NON_RESIDENT", "country": "DE", "pan": "AADCT1950F", "tax_id": "DE999999999", "trc_no": "TRC-DE-TEST-1",
                         "trc_valid_from": date(2027, 1, 1), "trc_valid_to": date(2028, 12, 31), "form10f_ack": "10F-TEST-DE-1",
                         "form10f_filed_on": date(2027, 4, 2), "form10f_valid_from": date(2027, 4, 1), "form10f_valid_to": date(2028, 3, 31),
                         "default_nature": "FTS"},
                        orders=[("4509950001", [("Test die design service A", "998331", 1, "5000.00", 18)]),
                                ("4509950002", [("Test die design service B", "998331", 1, "4000.00", 18)])]),
    "US": kit195.Vendor("T195US", "Testridge Software Inc (fictional test)", "US", "USD", "N30",
                        {"line1": "1 Test Way", "city": "Austin", "country": "US"},
                        {"account": "000000000195", "swift": "TESTUS33XXX", "bearer": "SHAR", "purpose": "S1006"},
                        {}, orders=[("4509950003", [("Test simulation software licence", "997331", 1, "2000.00", 18)])]),
    "AE": kit195.Vendor("T195AE", "Test Crest Consultancy FZE (fictional test)", "AE", "USD", "N30",
                        {"line1": "Tower T", "city": "Dubai", "country": "AE"},
                        {"account": "AE000000000000000195", "swift": "TESTAEADXXX", "bearer": "DEBT", "purpose": "S1007"},
                        {"residency": "NON_RESIDENT", "country": "AE", "pan": "AAHCT1950Q", "tax_id": "100000000000195", "trc_no": "UAE-TRC-TEST",
                         "trc_valid_from": date(2027, 1, 1), "trc_valid_to": date(2028, 12, 31), "form10f_ack": "10F-TEST-AE-1",
                         "form10f_filed_on": date(2027, 4, 2), "form10f_valid_from": date(2027, 4, 1), "form10f_valid_to": date(2028, 3, 31),
                         "gross_up": True, "default_nature": "FTS"},
                        orders=[("4509950004", [("Test energy audit", "998336", 1, "1000.00", 18)])]),
    "RES": kit195.Vendor("T195RES", "Test Valley Engineering Pvt Ltd (fictional test)", "IN", "INR", "N60",
                         {"line1": "Plot 1", "city": "Hosur", "state_code": "33", "pin": "635109", "country": "IN"},
                         {"account": "50200000000195", "ifsc": "TEST0000195"},
                         {"residency": "RESIDENT", "country": "IN"}, gstin="33AAKCT1950P1Z", tds_section="194J-TECH",
                         msme=("SMALL", "UDYAM-TN-31-0019500"),
                         orders=[("4509950005", [("Test fixture design", "998313", 1, "200000.00", 18)]),
                                 ("4509950006", [("Test PPAP study", "998313", 1, "100000.00", 18)]),
                                 ("4509950007", [("Test CMM programme", "998313", 1, "50000.00", 18)])]),
}
INV = {"DEa": ("DE", 0, "T195/DE/A"), "DEb": ("DE", 1, "T195/DE/B"), "USa": ("US", 0, "T195/US/A"), "AEa": ("AE", 0, "T195/AE/A"),
       "RESa": ("RES", 0, "T195/RES/A"), "RESb": ("RES", 1, "T195/RES/B"), "RESc": ("RES", 2, "T195/RES/C")}
J: dict = {}


def _problem(r, status, code=None):
    assert r.status_code == status, r.text
    body = r.json()
    if code:
        assert body["code"] == code, body
    return body


def _invoice(key: str) -> Invoice:
    vendor, _, no = INV[key]
    with tenant_tx(J["sc"].tenant_id) as s:
        inv = kit195.find_invoice(s, V[vendor].code, no)
        s.expunge(inv)
        return inv


def _ref(key: str) -> str:
    return quote(_invoice(key).number, safe="")


def _payments(key: str) -> list[Payment]:
    with tenant_tx(J["sc"].tenant_id) as s:
        rows = s.execute(select(Payment).where(Payment.invoice_id == _invoice(key).id, Payment.debit_note_id.is_(None))
                         .order_by(Payment.installment_no)).scalars().all()
        for r in rows:
            s.expunge(r)
        return rows


def _pin(day: date, hour: int = 10) -> None:
    clock.set_pinned(at(day, hour))


@pytest.fixture(scope="module", autouse=True)
def world(database, client, login):
    with system_tx() as s:
        sc = Scenario(s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one())
    J["sc"] = sc
    kit195.fx_rates(sc, [("EUR", DAY0, "90.0000"), ("USD", DAY0, "80.0000")])
    for key, spec in V.items():
        kit195.vendor(sc, spec, DAY0)
        for erp, lines in spec.orders:
            kit195.order(sc, spec, erp, lines, DAY0)
        if spec.residency:
            kit195.residency(sc, spec, DAY0)
    _pin(DAY0, 11)   # the US vendor's residency through the API (supplier manager)
    r = client.put(f"/v1/suppliers/{V['US'].code}/tax-residency", headers=login("supplier.manager"), json={
        "residency": "NON_RESIDENT", "country": "US", "pan": "AAGCT1950H", "taxId": "98-0000195", "trcNumber": "IRS-6166-TEST",
        "trcValidFrom": "2027-01-01", "trcValidTo": "2028-12-31", "form10fAcknowledgement": "10F-TEST-US-1", "form10fFiledOn": "2026-04-10",
        "form10fValidFrom": "2026-04-01", "form10fValidTo": "2027-03-31", "defaultNature": "ROYALTY", "reason": "TRC and Form 10F received (test)"})
    assert r.status_code == 200, r.text
    J["us_view"] = r.json()
    with tenant_tx(sc.tenant_id) as s:
        po = {erp: n for n, erp in s.execute(select(PurchaseOrder.number, PurchaseOrder.erp_doc_no).where(PurchaseOrder.erp_doc_no.like("450995%"))).all()}
    for key, (vendor, k, no) in INV.items():
        spec = V[vendor]
        kit195.invoice(sc, spec.code, po[spec.orders[k][0]], no, date(2028, 1, 4), date(2028, 1, 5), POST_DAY)
    kit195.debtor_rule(sc, DAY0)
    yield
    clock.set_pinned(None)


def test_residency_api_masks_and_encrypts(client, login):
    view = J["us_view"]
    assert view["residency"] == "NON_RESIDENT" and view["pan"].endswith("950H") and "AAGCT1950H" not in str(view)
    _pin(date(2028, 1, 6))
    got = client.get(f"/v1/suppliers/{V['US'].code}/tax-residency", headers=login("ap.clerk")).json()
    assert "TRC" in got["documentsValid"] and "FORM_10F" not in got["documentsValid"] and "not 2028-01-06" in got["documentsMissing"]["FORM_10F"]
    with tenant_tx(J["sc"].tenant_id) as s:
        row = s.execute(select(SupplierTaxResidency).join(Supplier, Supplier.id == SupplierTaxResidency.supplier_id)
                        .where(Supplier.code == V["US"].code)).scalar_one()
        assert b"AAGCT1950H" not in bytes(row.pan_enc) and nonresident_tax.pan_of(row) == "AAGCT1950H"
        event = s.execute(select(AuditEvent).where(AuditEvent.action == "TAX_RESIDENCY_CHANGED", AuditEvent.object_ref == V["US"].code)
                          .order_by(AuditEvent.seq.desc())).scalars().first()
        assert "AAGCT1950H" not in str(event.after) and "IRS-6166-TEST" not in str(event.after)
    bad = client.put(f"/v1/suppliers/{V['US'].code}/tax-residency", headers=login("supplier.manager"),
                     json={"residency": "NON_RESIDENT", "country": "IN", "reason": "wrong country test"})
    assert "other than IN" in _problem(bad, 422, "VALIDATION_FAILED")["detail"]
    assert client.put(f"/v1/suppliers/{V['US'].code}/tax-residency", headers=login("receiver"),
                      json={"residency": "RESIDENT", "country": "IN", "reason": "not allowed test"}).status_code == 403


def test_posting_fixes_the_provisional_195_determination():
    de, us, ae = _invoice("DEa"), _invoice("USa"), _invoice("AEa")
    assert de.status == "POSTED" and de.tds_section == "195-FTS" and de.tds_rate == Decimal("10.000") and de.withholding_tax_minor == 50_000
    assert us.tds_section == "195-ROYALTY" and us.tds_rate == Decimal("20.800") and us.withholding_tax_minor == 41_600
    assert ae.tds_section == "195-FTS" and ae.withholding_tax_minor == 26_263          # grossed up: 1,000 / 0.792 - 1,000
    res = _invoice("RESa")
    assert res.tds_section == "194J-TECH" and res.withholding_tax_minor == 4_000_00 and res.msme_capped is True
    with tenant_tx(J["sc"].tenant_id) as s:
        payload = s.execute(select(IntegrationMessage.payload).where(IntegrationMessage.object_id == de.id,
                                                                      IntegrationMessage.message_type == "SUPPLIER_INVOICE")).scalar_one()
        assert payload["tdsSection"] == "195-FTS" and payload["currency"] == "EUR"


def test_preview_endpoint_shows_the_breakdown(client, login):
    _pin(RUN1)
    r = client.get(f"/v1/invoices/{_ref('DEa')}/withholding-195", headers=login("finance.controller2"))
    assert r.status_code == 200, r.text
    body = r.json()
    d = body["determination"]
    assert body["applies"] and d["basis"] == "DTAA" and d["treaty"]["article"] == "12" and d["mock"] is True and d["taxMinor"] == 50_000
    assert d["taxInrMinor"] == 45_000_00 and Decimal(d["fxRate"]) == 90 and body["returnForm"] == "27Q"
    us = client.get(f"/v1/invoices/{_ref('USa')}/withholding-195", headers=login("finance.controller2")).json()["determination"]
    assert us["basis"] == "ACT" and "Form 10F covers" in us["treatyUnavailable"]
    assert client.get(f"/v1/invoices/{_ref('RESa')}/withholding-195", headers=login("finance.controller2")).json()["applies"] is False
    assert client.get(f"/v1/invoices/{_ref('DEa')}/withholding-195", headers=login("receiver")).status_code == 403


def test_remittance_without_form15ca_is_blocked_with_409(client, login):
    _pin(RUN1)
    de = _invoice("DEa").number
    proposal = client.post("/v1/payments/proposal", headers=login("finance.controller2"),
                           json={"run_date": RUN1.isoformat(), "include_not_due": True, "invoice_numbers": [de]}).json()
    assert proposal["skipped"][0]["code"] == "FORM_15CA_REQUIRED" and not proposal["items"]
    r = client.post("/v1/payments/runs", headers=login("finance.controller2"),
                    json={"run_date": RUN1.isoformat(), "include_not_due": True, "invoice_numbers": [de]})
    body = _problem(r, 409, "FORM_15CA_REQUIRED")
    assert r.headers["content-type"].startswith("application/problem+json") and body["invoice"] == de
    assert not _payments("DEa")                                        # nothing written, no ERP message


def test_form15_records_validation_and_dtaa_payment(client, login):
    _pin(RUN1, 9)
    de = _invoice("DEa").number
    url = f"/v1/invoices/{quote(de, safe='')}/form15"
    _problem(client.post(url, headers=login("finance.controller2"), json={"part": "C", "acknowledgement": "152028010000001", "filedOn": "2028-01-09",
                                                                          "amountMinor": 500_000}), 422, "VALIDATION_FAILED")   # part C needs 15CB
    assert client.post(url, headers=login("ap.clerk"), json={"part": "A", "acknowledgement": "152028010000001", "filedOn": "2028-01-09",
                                                             "amountMinor": 500_000}).status_code == 403
    ok = client.post(url, headers=login("finance.controller2"), json={"part": "A", "acknowledgement": "152028010000001", "filedOn": "2028-01-09",
                                                                      "amountMinor": 500_000})
    assert ok.status_code == 201, ok.text
    assert ok.json()["acknowledgement"].endswith("0001") and "152028010000001" not in ok.text
    _problem(client.post(url, headers=login("finance.controller2"), json={"part": "A", "acknowledgement": "152028010000001", "filedOn": "2028-01-09",
                                                                          "amountMinor": 500_000}), 409, "DUPLICATE_FORM15CA")
    _pin(RUN1)
    run = client.post("/v1/payments/runs", headers=login("finance.controller2"),
                      json={"run_date": RUN1.isoformat(), "include_not_due": True, "invoice_numbers": [de]})
    assert run.status_code == 200, run.text
    paid = run.json()["paid"][0]
    assert paid["tdsBasis"] == "DTAA" and paid["tdsMinor"] == 50_000 and paid["tdsInrMinor"] == 45_000_00 and paid["amountMinor"] == 450_000
    payment = _payments("DEa")[0]
    assert payment.tax_detail["treaty"]["article"] == "12" and payment.tds_base_inr_minor == 450_000_00 and payment.settles_invoice
    with tenant_tx(J["sc"].tenant_id) as s:
        form = s.execute(select(RemittanceCertificate).where(RemittanceCertificate.invoice_id == payment.invoice_id)).scalar_one()
        assert form.status == "USED" and form.payment_id == payment.id
        msg = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == f"PAY|{payment.number}")).scalar_one()
        assert msg.payload["tdsInrMinor"] == 45_000_00 and msg.payload["tdsBasis"] == "DTAA" and msg.payload["form15ca"].endswith("0001")
        assert msg.payload["withholdingSection"] == "195" and "partial" not in msg.payload
    assert _invoice("DEa").status == "PAID"


def test_form15cb_threshold_counts_the_fiscal_year(client, login):
    _pin(RUN2, 9)
    deb = _invoice("DEb").number   # 3,600 EUR after tax = 3,24,000 INR: with the 4,05,000 already remitted the year passes 5 lakh
    assert client.post(f"/v1/invoices/{quote(deb, safe='')}/form15", headers=login("finance.controller2"),
                       json={"part": "A", "acknowledgement": "152028010000002", "filedOn": "2028-01-16", "amountMinor": 400_000}).status_code == 201
    _pin(RUN2)
    _problem(client.post("/v1/payments/runs", headers=login("finance.controller2"),
                         json={"run_date": RUN2.isoformat(), "include_not_due": True, "invoice_numbers": [deb]}), 409, "FORM_15CB_REQUIRED")
    r = client.post(f"/v1/invoices/{quote(deb, safe='')}/form15", headers=login("finance.controller2"), json={
        "part": "C", "acknowledgement": "152028010000003", "filedOn": "2028-01-16", "amountMinor": 400_000, "form15cbCertificateNo": "28112233TESTUDIN01",
        "form15cbDate": "2028-01-15", "caName": "Test CA", "caMembershipNo": "200195"})
    assert r.status_code == 201, r.text
    run = client.post("/v1/payments/runs", headers=login("finance.controller2"),
                      json={"run_date": RUN2.isoformat(), "include_not_due": True, "invoice_numbers": [deb]})
    assert run.status_code == 200 and run.json()["paid"], run.text
    with tenant_tx(J["sc"].tenant_id) as s:
        used = s.execute(select(RemittanceCertificate).where(RemittanceCertificate.invoice_id == _invoice("DEb").id, RemittanceCertificate.status == "USED")).scalar_one()
        assert used.form15cb_certificate_no == "28112233TESTUDIN01"


def test_act_rate_and_gross_up_payments(client, login):
    _pin(RUN1, 9)
    for key, ack, amount in (("USa", "152028010000004", 200_000), ("AEa", "152028010000005", 100_000)):
        assert client.post(f"/v1/invoices/{_ref(key)}/form15", headers=login("finance.controller2"),
                           json={"part": "A", "acknowledgement": ack, "filedOn": "2028-01-09", "amountMinor": amount}).status_code == 201
    _pin(RUN1)
    run = client.post("/v1/payments/runs", headers=login("finance.controller2"), json={
        "run_date": RUN1.isoformat(), "include_not_due": True, "invoice_numbers": [_invoice("USa").number, _invoice("AEa").number]})
    assert run.status_code == 200, run.text
    us, ae = _payments("USa")[0], _payments("AEa")[0]
    assert us.tax_detail["basis"] == "ACT" and us.tds_minor == 41_600 and us.amount_minor == 158_400 and us.tds_inr_minor == 33_280_00
    assert ae.tax_detail["grossUp"] is True and ae.amount_minor == 100_000 and ae.tax_borne_minor == ae.tds_minor == 26_263
    assert ae.tds_base_minor == 126_263 and ae.tds_inr_minor == 21_010_00 and ae.tds_base_inr_minor == 101_010_10
    with tenant_tx(J["sc"].tenant_id) as s:
        msg = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == f"PAY|{ae.number}")).scalar_one()
        assert msg.payload["taxBorneByCompanyMinor"] == 26_263 and msg.payload["amountMinor"] == 100_000


def test_partial_payments_tds_once_erp_messages_and_bank_lines(client, login):
    res = _invoice("RESa").number
    _pin(RUN1)
    preview = client.post("/v1/payments/proposal", headers=login("finance.controller2"), json={
        "run_date": RUN1.isoformat(), "include_not_due": True, "invoice_numbers": [res],
        "partials": [{"invoice": res, "amountMinor": 100_000_00, "reason": "Milestone 1 of the fixture design accepted (test)"}]}).json()
    item = preview["items"][0]
    assert item["partial"] and item["openMinor"] == 232_000_00 and item["amountMinor"] == 100_000_00 and item["tdsMinor"] == 4_000_00
    runs = []
    for day, amount in ((RUN1, 100_000_00), (RUN2, 50_000_00), (RUN3, None)):
        _pin(day)
        body = {"run_date": day.isoformat(), "include_not_due": True, "invoice_numbers": [res]}
        if amount:
            body["partials"] = [{"invoice": res, "amountMinor": amount, "reason": "Milestone billing agreed with the vendor (test)"}]
        r = client.post("/v1/payments/runs", headers=login("finance.controller2"), json=body)
        assert r.status_code == 200 and r.json()["paid"], r.text
        runs.append(r.json())
        inv = _invoice("RESa")
        assert inv.payment_status == ("PARTIALLY_PAID" if amount else "PAID") and inv.status == ("POSTED" if amount else "PAID")
    pays = _payments("RESa")
    assert [p.installment_no for p in pays] == [1, 2, 3] and [p.settles_invoice for p in pays] == [False, False, True]
    assert [p.amount_minor for p in pays] == [100_000_00, 50_000_00, 82_000_00]
    assert [p.tds_minor for p in pays] == [4_000_00, 0, 0]                              # TDS deducted once, with the first part
    assert pays[0].partial_reason.startswith("Milestone") and runs[2]["paid"][0]["installment"] == 3 and runs[2]["paid"][0]["partial"] is False
    inv = _invoice("RESa")
    assert inv.paid_minor == 232_000_00 and inv.due_date == inv.acceptance_date + (inv.due_date - inv.acceptance_date) and inv.msme_capped
    with tenant_tx(J["sc"].tenant_id) as s:
        msgs = {m.idempotency_key: m.payload for m in s.execute(select(IntegrationMessage).where(IntegrationMessage.message_type == "PAYMENT",
                                                                                                   IntegrationMessage.object_id == inv.id)).scalars()}
        first, second, last = (msgs[f"PAY|{p.number}"] for p in pays)
        assert first["partial"] is True and first["tdsMinor"] == 4_000_00 and first["openAfterMinor"] == 132_000_00
        assert second["installment"] == 2 and "tdsMinor" not in second and second["paidBeforeMinor"] == 100_000_00
        assert last["partial"] is False and last["openAfterMinor"] == 0
        events = s.execute(select(AuditEvent.action).where(AuditEvent.object_id == inv.id)).scalars().all()
        assert events.count("PARTIAL_PAYMENT") == 2 and events.count("PARTIAL_PAYMENT_CLEARED") == 2
    # every part is its own bank-file line
    _pin(RUN3, 12)
    f = client.post(f"/v1/payments/runs/{runs[1]['run']}/file", headers=login("finance.controller2"), json={"format": "ISO20022_PAIN001"})
    assert f.status_code == 201, f.text
    content = client.get(f"/v1/payment-files/{f.json()['number']}/content", headers=login("finance.controller2")).text
    assert pays[1].number in content and "50000.00" in content
    # the invoice view shows paid / open and the parts
    view = client.get(f"/v1/invoices/{quote(res, safe='')}", headers=login("ap.clerk")).json()["settlement"]
    assert view["paidMinor"] == 232_000_00 and view["openMinor"] == 0 and len(view["installments"]) == 3


def test_partial_validation_and_early_payment_rules(client, login):
    resb = _invoice("RESb").number
    _pin(RUN1)

    def run(amount, reason="Release against the PPAP milestone (test)"):
        return client.post("/v1/payments/runs", headers=login("finance.controller2"), json={
            "run_date": RUN1.isoformat(), "include_not_due": True, "invoice_numbers": [resb],
            "partials": [{"invoice": resb, "amountMinor": amount, "reason": reason}]})
    assert "more than the open amount" in _problem(run(200_000_00), 422, "PARTIAL_NOT_ALLOWED")["detail"]
    assert "reason" in _problem(run(40_000_00, reason="short"), 422, "PARTIAL_NOT_ALLOWED")["detail"]
    assert "at least" in _problem(run(500), 422, "PARTIAL_NOT_ALLOWED")["detail"]
    _problem(client.post("/v1/payments/runs", headers=login("finance.controller2"), json={
        "run_date": RUN1.isoformat(), "invoice_numbers": [resb], "partials": [{"invoice": _invoice("RESc").number, "amountMinor": 100, "reason": "x" * 12}]}),
        422, "VALIDATION_FAILED")                                                       # partial outside the selection
    assert not _payments("RESb")
    # an accepted early-payment discount is earned only by the whole invoice
    with tenant_tx(J["sc"].tenant_id) as s:
        row = s.get(Invoice, _invoice("RESc").id)
        row.payment_option, row.discount_minor = "EARLY_DISCOUNT", 500_00
    try:
        resc = _invoice("RESc").number
        r = client.post("/v1/payments/runs", headers=login("finance.controller2"), json={
            "run_date": RUN1.isoformat(), "include_not_due": True, "invoice_numbers": [resc],
            "partials": [{"invoice": resc, "amountMinor": 10_000_00, "reason": "Part payment requested by the vendor (test)"}]})
        assert "whole invoice" in _problem(r, 422, "PARTIAL_NOT_ALLOWED")["detail"]
    finally:
        with tenant_tx(J["sc"].tenant_id) as s:
            row = s.get(Invoice, _invoice("RESc").id)
            row.payment_option, row.discount_minor = "STANDARD", 0
    # a partially paid invoice takes no early-payment offer
    sc = J["sc"]
    with sc.act("finance.controller2", at(RUN1, 11)) as s:
        payables.payment_run(s, RUN1, include_not_due=True, invoice_numbers=[resb],
                             partials={resb: {"amountMinor": 40_000_00, "reason": "Release against the PPAP milestone (test)"}})
    with sc.act("ap.clerk", at(RUN1, 12)) as s:
        with pytest.raises(Problem):
            early_payment.make_offer(s, s.get(Invoice, _invoice("RESb").id), discount_pct=Decimal("1"), pay_on=date(2028, 1, 20), note="test")


def test_returned_partial_reopens_its_amount_and_its_tds(client, login):
    sc = J["sc"]
    resb = _invoice("RESb").number
    with sc.act("finance.controller2", at(RUN2, 10)) as s:
        result = payables.payment_run(s, RUN2, include_not_due=True, invoice_numbers=[resb],
                                      partials={resb: {"amountMinor": 30_000_00, "reason": "Second milestone of the PPAP study (test)"}})
        assert result["paid"][0]["installment"] == 2 and result["paid"][0]["tdsMinor"] == 0
    first = _payments("RESb")[0]
    assert first.tds_minor == 2_000_00 and _invoice("RESb").paid_minor == 70_000_00
    with sc.act("finance.controller2", at(RETURN_DAY, 10)) as s:
        payables.return_payment(s, s.get(Payment, first.id), "AC04 account closed (test)")
    inv = _invoice("RESb")
    assert inv.payment_status == "PARTIALLY_PAID" and inv.paid_minor == 30_000_00
    with sc.act("finance.controller2", at(RUN3, 9)) as s:
        assert payables.open_amount(s, s.get(Invoice, inv.id), RUN3) == 86_000_00     # 1,18,000 - TDS 2,000 (again due) - 30,000
    _pin(RUN3)
    r = client.post("/v1/payments/runs", headers=login("finance.controller2"),
                    json={"run_date": RUN3.isoformat(), "include_not_due": True, "invoice_numbers": [resb]})
    assert r.status_code == 200 and r.json()["paid"][0]["amountMinor"] == 86_000_00 and r.json()["paid"][0]["tdsMinor"] == 2_000_00, r.text
    pays = _payments("RESb")
    live = [p for p in pays if p.status != "CANCELLED"]
    assert [p.installment_no for p in pays] == [1, 2, 3] and pays[0].status == "CANCELLED" and pays[0].bank_status == "RETURNED"
    assert sum(p.tds_minor for p in live) == 2_000_00 and _invoice("RESb").status == "PAID"           # deducted once overall
    with tenant_tx(sc.tenant_id) as s:
        event = s.execute(select(AuditEvent).where(AuditEvent.action == "PAYMENT_RETURNED", AuditEvent.object_id == inv.id)).scalars().first()
        assert event.after["installment"] == 1 and event.after["paymentStatus"] == "PARTIALLY_PAID"


def test_sod_still_applies_to_partial_payments(client, login):
    resc = _invoice("RESc").number      # approved by finance.controller: SOD-09, the approver cannot release its payment
    _pin(RUN1)
    proposal = client.post("/v1/payments/proposal", headers=login("finance.controller"), json={
        "run_date": RUN1.isoformat(), "include_not_due": True, "invoice_numbers": [resc],
        "partials": [{"invoice": resc, "amountMinor": 10_000_00, "reason": "Part payment requested by the vendor (test)"}]}).json()
    assert proposal["skipped"] and "SOD" in proposal["skipped"][0]["reason"]
    r = client.post("/v1/payments/runs", headers=login("finance.controller"), json={
        "run_date": RUN1.isoformat(), "include_not_due": True, "invoice_numbers": [resc],
        "partials": [{"invoice": resc, "amountMinor": 10_000_00, "reason": "Part payment requested by the vendor (test)"}]})
    assert r.status_code == 200 and not r.json()["paid"] and "SOD" in r.json()["skipped"][0]["reason"]
    assert client.post("/v1/payments/runs", headers=login("ap.clerk"), json={"run_date": RUN1.isoformat(), "invoice_numbers": [resc]}).status_code == 403


def test_returns_split_26q_and_27q(client, login):
    sc = J["sc"]
    with sc.act("finance.controller2", at(date(2028, 2, 5), 10)) as s:
        data = tds_returns.certificate_data(s, FY, Q, company_codes=["1000"])
        mine = {c["deductee"]["supplier"]: c for c in data["certificates"] if c["deductee"]["supplier"].startswith("T195")}
        assert mine["T195DE"]["returnForm"] == "27Q" and mine["T195DE"]["deductee"]["pan"] == "AADCT1950F" and mine["T195DE"]["deductee"]["country"] == "DE"
        assert mine["T195DE"]["totals"]["taxDeductedMinor"] == 45_000_00 + 36_000_00          # INR: 10 % of 4,50,000 and of 3,60,000
        assert mine["T195DE"]["payments"][0]["basis"] == "DTAA" and mine["T195DE"]["payments"][0]["currency"] == "EUR"
        assert mine["T195RES"]["returnForm"] == "26Q" and mine["T195RES"]["deductee"]["pan"] == "AAKCT1950P"
        assert mine["T195RES"]["totals"]["taxDeductedMinor"] == 6_000_00
        challan = tds_returns.record_challan(s, company_code="1000", fiscal_year=FY, quarter=Q, section="195-FTS", challan_no="19501", bsr_code="0510308",
                                             deposit_date=date(2028, 2, 5), amount_minor=81_000_00)
        assert challan.section == "195-FTS"
        recon = tds_returns.reconciliation(s, FY, Q, ["1000"])
        row = next(r for r in recon["rows"] if r["section"] == "195-FTS")
        assert row["returnForm"] == "27Q" and row["depositedMinor"] >= 81_000_00 and recon["byReturnForm"]["27Q"]["deductedMinor"] >= row["deductedMinor"]
    _pin(date(2028, 2, 5))
    q27 = client.get(f"/v1/finance/tds-export?fiscal_year={FY}&quarter={Q}&format=27Q", headers=login("finance.controller2"))
    assert q27.status_code == 200 and "T195DE" in q27.text and "DTAA" in q27.text and "T195RES" not in q27.text
    q26 = client.get(f"/v1/finance/tds-export?fiscal_year={FY}&quarter={Q}&format=26Q", headers=login("finance.controller2"))
    assert "T195RES" in q26.text and "T195DE" not in q26.text


def test_form16a_pdf_endpoint(client, login):
    _pin(date(2028, 2, 6))
    url = f"/v1/finance/tds-certificates/pdf?fiscal_year={FY}&quarter={Q}&supplier="
    r = client.get(url + "T195RES", headers=login("finance.controller2"))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and "FORM16A_INFO_T195RES" in r.headers["content-disposition"]
    assert b"Information copy \x97 the statutory Form 16A must be downloaded from TRACES" in r.content and b"AAKCT1950P" in r.content
    nr = client.get(url + "T195DE", headers=login("finance.controller2"))
    assert b"Form 27Q" in nr.content and b"AADCT1950F" in nr.content and b"DTAA" in nr.content
    assert client.get(url + "T195US-NONE", headers=login("finance.controller2")).status_code == 404
    assert client.get(url + "T195RES", headers=login("ap.clerk")).status_code == 403
    with tenant_tx(J["sc"].tenant_id) as s:   # a finance user scoped to another company code sees no certificate of company code 1000 (ABAC)
        if s.execute(select(AppUser.id).where(AppUser.email == "fin.scoped.t195@axion.example")).first() is None:
            s.add(AppUser(tenant_id=J["sc"].tenant_id, email="fin.scoped.t195@axion.example", full_name="Scoped Finance (test)",
                          password_hash=hash_password(PASSWORD), roles=["FINANCE_CONTROLLER"], attributes={"company_codes": ["2000"]}, mfa_enrolled=True))
    assert client.get(url + "T195RES", headers=login("fin.scoped.t195")).status_code == 404
    with tenant_tx(J["sc"].tenant_id) as s:
        assert s.execute(select(AuditEvent).where(AuditEvent.object_ref == f"{FY}/{Q}/16A-PDF/T195RES")).scalars().first() is not None


def test_effective_dated_rule_and_invoice_nature(client, login):
    sc = J["sc"]
    with tenant_tx(sc.tenant_id) as s:
        if not s.execute(select(RuleSet.id).where(RuleSet.key == "TDS-195", RuleSet.version == "2028.03-TEST")).first():
            body = copy.deepcopy(finance_defaults.TDS_195_DEFAULT)
            body["dtaa"]["DE"]["FTS"] = {"ratePct": 5, "article": "12"}
            s.add(RuleSet(tenant_id=sc.tenant_id, key="TDS-195", version="2028.03-TEST", effective_from=date(2028, 3, 1), body=body,
                          description="test: treaty rate changed from March 2028"))
    head = login("finance.controller2")
    _pin(date(2028, 2, 10))
    resc = _invoice("RESc").number
    assert client.get(f"/v1/invoices/{_ref('DEb')}/withholding-195?on=2028-02-20", headers=head).json()["determination"]["ratePct"] == "10.0000"
    assert client.get(f"/v1/invoices/{_ref('DEb')}/withholding-195?on=2028-03-02", headers=head).json()["determination"]["ratePct"] == "5.0000"
    # the nature of a non-resident's invoice can be changed until it is paid; a resident's cannot be set
    _problem(client.put(f"/v1/invoices/{quote(resc, safe='')}/withholding-195", headers=head, json={"nature": "FTS", "reason": "test resident"}), 409, "NOT_NON_RESIDENT")
    _problem(client.put(f"/v1/invoices/{_ref('DEa')}/withholding-195", headers=head, json={"nature": "ROYALTY", "reason": "already paid test"}),
             409, "ILLEGAL_TRANSITION")
    with sc.act("finance.controller2", at(date(2028, 2, 10), 10)) as s:
        assert settlement.position(s, s.get(Invoice, _invoice("DEa").id))["openMinor"] == 0


def test_service_validation_paths():
    sc = J["sc"]
    day = date(2028, 2, 12)

    def problem(fn) -> Problem:
        with pytest.raises(Problem) as exc:
            fn()
        return exc.value
    with sc.act("supplier.manager", at(day, 10)) as s:
        sup = s.execute(select(Supplier).where(Supplier.code == V["DE"].code)).scalar_one()
        err = problem(lambda: nonresident_tax.set_residency(s, sup, residency="ALIEN", country="germany", payee_type="TRUST", reason="bad data test",
                                                            pan="123", trc_no="?", trc_valid_from=date(2028, 1, 2), trc_valid_to=date(2028, 1, 1),
                                                            form10f_ack="10F-X-1", form10f_valid_from=date(2028, 2, 2), form10f_valid_to=date(2028, 2, 1),
                                                            no_pe_valid_from=date(2028, 2, 2), no_pe_valid_to=date(2028, 2, 1), default_nature="DIVIDEND",
                                                            clear=("gstin",)))
        assert err.status == 422 and len(err.extra["errors"]) >= 9
        assert problem(lambda: nonresident_tax.set_residency(s, sup, residency="NON_RESIDENT", country="DE", reason="x")).code == "REASON_REQUIRED"
        assert problem(lambda: nonresident_tax.set_residency(s, sup, residency="RESIDENT", country="DE", reason="wrong country")).status == 422
        row = nonresident_tax.set_residency(s, sup, reason="tax id withdrawn (test)", clear=("tax_id",), **{k: v for k, v in V["DE"].residency.items()
                                                                                                       if k != "tax_id"})
        assert row.tax_id_enc is None and row.pan_enc is not None and "TAX_ID" in nonresident_tax.view(s, row, sup)["documentsMissing"]
        nonresident_tax.set_residency(s, sup, reason="tax id restored (test)", **V["DE"].residency)
        assert nonresident_tax.view(s, None, sup)["residency"] is None
    with sc.act("finance.controller2", at(day, 11)) as s:
        dea, resc = s.get(Invoice, _invoice("DEa").id), s.get(Invoice, _invoice("RESc").id)
        assert problem(lambda: nonresident_tax.record_form15(s, resc, part="A", acknowledgement="152028020000001", filed_on=day, amount_minor=100)).code == "NOT_NON_RESIDENT"
        assert problem(lambda: nonresident_tax.record_form15(s, dea, part="A", acknowledgement="152028020000001", filed_on=day, amount_minor=100)).code == "ILLEGAL_TRANSITION"
        deb_open = s.get(Invoice, _invoice("DEb").id)
        deb_open.status, deb_open.payment_status, deb_open.paid_minor = "POSTED", "UNPAID", 0   # scratch state, rolled back below
        err = problem(lambda: nonresident_tax.record_form15(s, deb_open, part="X", acknowledgement="bad!", filed_on=date(2030, 1, 1), amount_minor=0,
                                                            form15cb_certificate_no="??", form15cb_date=None))
        assert err.status == 422 and len(err.extra["errors"]) >= 5
        err = problem(lambda: nonresident_tax.record_form15(s, deb_open, part="C", acknowledgement="152028020000009", filed_on=day, amount_minor=100,
                                                            form15cb_certificate_no="28112233TESTUDIN99", form15cb_date=day + timedelta(days=1),
                                                            ca_name="CA", ca_membership_no="123456"))
        assert "certified before" in err.detail
        form = nonresident_tax.record_form15(s, deb_open, part="A", acknowledgement="152028020000010", filed_on=day, amount_minor=100)
        assert problem(lambda: nonresident_tax.void_form15(s, deb_open, form.id, "no")).code == "REASON_REQUIRED"
        assert problem(lambda: nonresident_tax.void_form15(s, deb_open, uuid.uuid4(), "unknown form test")).code == "NOT_FOUND"
        assert nonresident_tax.void_form15(s, deb_open, form.id, "entered in error (test)").status == "VOID"
        assert problem(lambda: nonresident_tax.void_form15(s, deb_open, form.id, "again (test)")).code == "ILLEGAL_TRANSITION"
        assert problem(lambda: nonresident_tax.set_invoice_tax(s, deb_open, nature="FTS", gross_up=None, reason="no")).code == "REASON_REQUIRED"
        assert problem(lambda: nonresident_tax.set_invoice_tax(s, deb_open, nature="DIVIDEND", gross_up=None, reason="unknown nature test")).code == "TDS_195_NATURE_UNKNOWN"
        nonresident_tax.set_invoice_tax(s, deb_open, nature="ROYALTY", gross_up=True, reason="nature corrected (test)")
        assert deb_open.tds_section == "195-ROYALTY" and deb_open.tax_gross_up is True
        preview = nonresident_tax.invoice_preview(s, deb_open, day)
        assert preview["determination"]["grossUp"] is True and preview["determination"]["basis"] == "DTAA"
        s.rollback()
    with sc.act("receiver", at(day, 12)) as s:
        sup = s.execute(select(Supplier).where(Supplier.code == V["DE"].code)).scalar_one()
        assert problem(lambda: nonresident_tax.set_residency(s, sup, residency="RESIDENT", country="IN", reason="not allowed")).status == 403
        assert problem(lambda: nonresident_tax.record_form15(s, s.get(Invoice, _invoice("DEb").id), part="A", acknowledgement="152028020000011",
                                                              filed_on=day, amount_minor=1)).status == 403
        assert problem(lambda: nonresident_tax.set_invoice_tax(s, s.get(Invoice, _invoice("DEb").id), nature="FTS", gross_up=None,
                                                               reason="not allowed")).status == 403
        assert problem(lambda: nonresident_tax.void_form15(s, s.get(Invoice, _invoice("DEb").id), uuid.uuid4(), "not allowed")).status == 403
