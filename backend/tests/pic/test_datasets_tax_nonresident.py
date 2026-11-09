"""D23 dataset pack tax_nonresident (AXN, October 2027): non-resident vendors under section 195, the Form 15CA / 15CB checkpoint, partial payments
with a returned part, challans and Form 16A information copies. MOCK, ILLUSTRATIVE SAMPLE.

The tests assert the end state of every scenario of the pack and that the AXN documents that existed before it are unchanged."""
import hashlib
import json
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (AuditEvent, Invoice, Payment, PaymentFile, RemittanceCertificate, RuleSet, Supplier, SupplierTaxResidency, TdsChallan,
                            Tenant)
from app.pic.platform import clock
from app.pic.seed import datasets
from app.pic.seed.axion import Scenario, at
from app.pic.seed.datasets import tax_nonresident as pack
from app.pic.services import nonresident_tax, tds_returns
from tests.pic.conftest import PASSWORD

CODES = {v.code for v in pack.VENDORS}


def _hashes(s, supplier_ids: set) -> dict:
    out = {}
    for model in (Invoice, Payment):
        for row in s.execute(select(model).where(model.supplier_id.notin_(supplier_ids)).order_by(model.id)).scalars():
            values = {c.key: getattr(row, c.key) for c in model.__mapper__.column_attrs if c.key not in ("updated_at", "row_version")}
            out[(model.__tablename__, str(row.id))] = hashlib.sha256(json.dumps(values, default=str, sort_keys=True).encode()).hexdigest()
    return out


@pytest.fixture(scope="module")
def loaded(database):
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    with tenant_tx(tenant_id) as s:
        before = _hashes(s, set())
    results = datasets.apply_pack("tax_nonresident", PASSWORD)
    assert [r["status"] for r in results] == ["LOADED"], results
    with tenant_tx(tenant_id) as s:
        mine = set(s.execute(select(Supplier.id).where(Supplier.code.in_(CODES))).scalars())
        after = _hashes(s, mine)
    yield {"tenant_id": tenant_id, "result": results[0], "before": before, "after": after, "sc": Scenario(tenant_id)}
    clock.set_pinned(None)


def _inv(s, key: str) -> Invoice:
    _, code, _, no = next(x for x in pack.INVOICES if x[0] == key)
    return pack.find_invoice(s, code, no)


def _pays(s, key: str) -> list[Payment]:
    return s.execute(select(Payment).where(Payment.invoice_id == _inv(s, key).id, Payment.debit_note_id.is_(None))
                     .order_by(Payment.installment_no)).scalars().all()


def test_registration_and_idempotency(loaded):
    assert "tax_nonresident" in datasets.PACKS and datasets.PACKS.index("tax_nonresident") > datasets.PACKS.index("org_masters")
    assert pack.KEY == "tax-nonresident" and pack.READY and pack.REQUIRES and "MOCK" in pack.TITLE
    assert datasets.apply_pack("tax_nonresident", PASSWORD)[0]["status"] == "ALREADY_LOADED"
    with tenant_tx(loaded["tenant_id"]) as s:
        payments = len(s.execute(select(Payment.id).where(Payment.supplier_id.in_(select(Supplier.id).where(Supplier.code.in_(CODES))))).all())
    forced = datasets.apply_pack("tax_nonresident", PASSWORD, force=True)
    assert forced[0]["status"] == "LOADED"
    with tenant_tx(loaded["tenant_id"]) as s:
        assert len(s.execute(select(Payment.id).where(Payment.supplier_id.in_(select(Supplier.id).where(Supplier.code.in_(CODES))))).all()) == payments
        assert len(s.execute(select(Invoice.id).where(Invoice.supplier_id.in_(select(Supplier.id).where(Supplier.code.in_(CODES))))).all()) == len(pack.INVOICES)


def test_existing_axn_documents_unchanged(loaded):
    before, after = loaded["before"], loaded["after"]
    assert set(before) == set(after) and all(before[k] == after[k] for k in before)


def test_vendors_and_tax_residency(loaded):
    with tenant_tx(loaded["tenant_id"]) as s:
        rows = {sup.code: (sup, res) for sup, res in s.execute(select(Supplier, SupplierTaxResidency).join(
            SupplierTaxResidency, SupplierTaxResidency.supplier_id == Supplier.id).where(Supplier.code.in_(CODES))).all()}
        assert set(rows) == CODES
        assert {c for c, (_, r) in rows.items() if r.residency == "NON_RESIDENT"} == {"NRDE01", "NRUS01", "NRSG01", "NRAE01"}
        de, us, sg, ae = (rows[c][1] for c in ("NRDE01", "NRUS01", "NRSG01", "NRAE01"))
        assert nonresident_tax.pan_of(de) == "AADCR4410F" and b"AADCR4410F" not in bytes(de.pan_enc) and de.pan_masked.endswith("410F")
        assert sg.pan_enc is None and sg.tax_id_enc is None and ae.gross_up is True
        assert us.form10f_valid_to.isoformat() == "2027-03-31" and us.trc_valid_to.isoformat() == "2027-12-31"
        assert all("fictional" in sup.legal_name for sup, _ in rows.values())
        rule = s.execute(select(RuleSet).where(RuleSet.key == "TDS", RuleSet.version == "2027.10-AXN-DEDUCTOR-MOCK")).scalar_one()
        assert rule.body["deductor"]["tan"] and "MOCK" in rule.description


def test_every_invoice_stays_below_the_finance_controller_band(loaded):
    """Pack approval_bands (D22) puts invoices of 10 lakh or more (gross, company-code currency) through the finance controller and the CFO:
    the pack's invoices stay below it, so they are approved by accounts payable alone whether or not D22 is loaded."""
    with tenant_tx(loaded["tenant_id"]) as s:
        for key, *_ in pack.INVOICES:
            inv = _inv(s, key)
            assert (inv.gross_group_minor or inv.gross_minor) < 10 * 100_000 * 100 and inv.status in ("POSTED", "PAID"), key


def test_treaty_act_no_pan_and_gross_up(loaded):
    with tenant_tx(loaded["tenant_id"]) as s:
        de1, = _pays(s, "DE1")
        assert de1.tax_detail["basis"] == "DTAA" and Decimal(de1.tax_detail["ratePct"]) == 10 and de1.tds_minor == 84_000 and de1.amount_minor == 756_000
        assert de1.tds_inr_minor == 77_616_00 and _inv(s, "DE1").status == "PAID"
        us1, = _pays(s, "US1")
        assert us1.tax_detail["basis"] == "ACT" and us1.tax_detail["ratePct"] == "20.8000" and us1.value_date.isoformat() == "2027-10-19"
        assert "Form 10F" in us1.tax_detail["treatyUnavailable"] and us1.tds_minor == 197_600
        sg1, = _pays(s, "SG1")
        assert sg1.tax_detail["basis"] == "NO_PAN_206AA" and sg1.tax_detail["noPan"] is True and sg1.tax_detail["noPanReliefMissing"]
        ae1, = _pays(s, "AE1")
        assert ae1.tax_detail["grossUp"] is True and ae1.amount_minor == 700_000 and ae1.tax_borne_minor == ae1.tds_minor > 0
        assert ae1.tds_base_minor == ae1.amount_minor + ae1.tds_minor
        assert all(p.currency != "INR" and p.fx_rate for p in (de1, us1, sg1, ae1))


def test_form15_checkpoint(loaded):
    with tenant_tx(loaded["tenant_id"]) as s:
        refused = s.execute(select(AuditEvent).where(AuditEvent.action == "TAX_NONRESIDENT_STAGE", AuditEvent.object_ref == "run-a-refused")).scalars().first()
        assert refused.after["refused"] is True and refused.after["status"] == 409 and refused.after["code"] == "FORM_15CA_REQUIRED"
        forms = s.execute(select(RemittanceCertificate)).scalars().all()
        used = {f.invoice_id for f in forms if f.status == "USED" and f.supplier_id in set(s.execute(select(Supplier.id).where(Supplier.code.in_(CODES))).scalars())}
        assert {_inv(s, k).id for k in ("DE1", "US1", "SG1", "AE1")} <= used
        assert all(f.form15cb_certificate_no for f in forms if f.invoice_id in used)
        de2 = _inv(s, "DE2")
        assert de2.status == "POSTED" and de2.payment_status == "UNPAID" and not _pays(s, "DE2")
    skipped = pack.proposal_skips(loaded["sc"], de2.number)
    assert skipped and skipped[0]["code"] == "FORM_15CA_REQUIRED"


def test_partial_payments_and_the_returned_part(loaded):
    with tenant_tx(loaded["tenant_id"]) as s:
        r1 = _pays(s, "R1")
        assert [p.amount_minor for p in r1] == [250_000_00, 200_000_00, 246_000_00] and [p.tds_minor for p in r1] == [12_000_00, 0, 0]
        assert [p.settles_invoice for p in r1] == [False, False, True] and all(p.partial_reason for p in r1[:2])
        assert _inv(s, "R1").status == "PAID" and _inv(s, "R1").paid_minor == 696_000_00 and _inv(s, "R1").msme_capped
        r2 = _pays(s, "R2")
        assert [p.installment_no for p in r2] == [1, 2, 3] and r2[0].status == "CANCELLED" and r2[0].bank_status == "RETURNED"
        assert [p.amount_minor for p in r2] == [100_000_00, 80_000_00, 268_000_00] and r2[2].tds_minor == 6_000_00
        assert sum(p.tds_minor for p in r2 if p.status != "CANCELLED") == 6_000_00 and _inv(s, "R2").status == "PAID"
        files = s.execute(select(PaymentFile).where(PaymentFile.run_ref.in_({p.run_ref for p in r1}))).scalars().all()
        assert len(files) == 3                                        # one bank file per run, a line per part


def test_challans_reconcile_and_16a_copies(loaded):
    with pack._scenario().act("finance.controller2", at(pack.CHALLAN_DAY, 16)) as s:
        recon = tds_returns.reconciliation(s, pack.FY, pack.QUARTER, ["1000"])
        rows = {r["section"]: r for r in recon["rows"]}
        for section in ("194J-TECH", "195-FTS", "195-ROYALTY"):
            assert rows[section]["differenceMinor"] == 0 and rows[section]["depositedMinor"] > 0
        assert rows["195-FTS"]["returnForm"] == "27Q" and rows["194J-TECH"]["returnForm"] == "26Q" and recon["byReturnForm"]["27Q"]["depositedMinor"] > 0
        assert s.execute(select(TdsChallan).where(TdsChallan.fiscal_year == pack.FY, TdsChallan.quarter == pack.QUARTER)).first() is not None
        data = tds_returns.certificate_data(s, pack.FY, pack.QUARTER, company_codes=["1000"])
        mine = {c["deductee"]["supplier"]: c for c in data["certificates"] if c["deductee"]["supplier"] in CODES}
        assert mine["RVES01"]["returnForm"] == "26Q" and mine["RVES01"]["missingMandatory"] == [] and mine["RVES01"]["totals"]["taxDepositedMinor"] > 0
        assert mine["NRDE01"]["returnForm"] == "27Q" and mine["NRSG01"]["deductee"]["pan"] == "PANNOTAVBL"
        pdf = tds_returns.certificate_pdf(data, "RVES01")
        assert pdf.startswith(b"%PDF-1.4") and b"must be downloaded from TRACES" in pdf and b"CHEA99999Z" in pdf
        assert b"Form 27Q" in tds_returns.certificate_pdf(data, "NRUS01")


def test_import_of_services_is_reverse_charge_and_categories_are_mapped(loaded):
    """A service bought from a supplier outside India is an import of services: the supplier charges no Indian GST and AXN self-assesses IGST 18 %
    under reverse charge (IGST Act s.5(3)); the resident supplier charges GST as usual. Every vendor's category is one the UNSPSC mapping covers,
    so the reference-data pack (D11) finds no unmapped category and no HSN/SAC used at a rate the CBIC schedule does not allow."""
    from types import SimpleNamespace

    from app.pic.models import SupplierCategoryStatus
    from app.pic.seed.datasets.reference_data import unspsc_body
    from app.pic.services import gst

    assert gst.reverse_charge(None, SimpleNamespace(country="DE", gstin_enc=None), "998331") is True
    with tenant_tx(loaded["tenant_id"]) as s:
        assert gst.reverse_charge(s, SimpleNamespace(country="DE", gstin_enc=None), "84807100") is False  # imported goods: IGST at customs
        assert gst.reverse_charge(s, SimpleNamespace(country="ZZ", gstin_enc=None), "998331") is False
        for key, code, *_ in pack.INVOICES:
            inv = _inv(s, key)
            if code.startswith("NR"):
                assert (inv.tax_minor, inv.reverse_charge) == (0, True) and inv.rcm_tax_minor == round(inv.net_minor * Decimal("0.18")), key
                assert inv.gross_minor == inv.net_minor, key
            else:
                assert inv.reverse_charge is False and inv.tax_minor == round(inv.net_minor * Decimal("0.18")), key
        nodes = unspsc_body()["nodes"]
        categories = set(s.execute(select(SupplierCategoryStatus.category).join(Supplier, Supplier.id == SupplierCategoryStatus.supplier_id)
                                   .where(Supplier.code.in_(CODES))).scalars())
        assert categories and categories <= set(nodes), categories - set(nodes)
