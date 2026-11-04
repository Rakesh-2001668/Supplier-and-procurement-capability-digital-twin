"""D12 contract portfolio of tenant KAC (ILLUSTRATIVE SAMPLE, fictional contracts) loaded from the mock contract-register export.

Determinism of the generator, counts by type and status, call-offs under master agreements, every clause taken from the clause library
(standard, pre-approved fallback and non-standard wording), obligations (on time, late, overdue) and milestones, the renewals list at 30 / 90 / 120
days, a contract in negotiation with supplier redlines, a terminated one, amendment histories, rebate tiers, signed documents bound to the hash of
the loaded text, the CLM-02 clause review of a risky contract, and an idempotent second apply.
"""
import json
from collections import Counter
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import Clause, Contract, ContractAmendment, ContractLine, Obligation, PriceValidity, RebateAgreement, Signature, Supplier, Tenant, Timer
from app.pic.platform import clock, rules
from app.pic.seed import clause_library, datasets
from app.pic.seed.axion import at
from app.pic.services import contract as contract_svc
from app.pic.tools import contract_load, erp_mock_contracts
from tests.pic.conftest import PASSWORD

TODAY = date(2026, 11, 1)


@pytest.fixture(scope="module")
def loaded(database):
    first = datasets.apply_pack("erp_client_kac", PASSWORD)          # the SAP cutover first (already loaded when the SAP-extract test ran)
    assert first[0]["status"] in ("LOADED", "ALREADY_LOADED"), first
    results = datasets.apply_pack("contracts_kac", PASSWORD)
    assert results[0]["status"] in ("LOADED", "ALREADY_LOADED"), results
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == "KAC")).scalar_one()
    clock.set_pinned(at(TODAY, 9))
    yield {"tenant_id": tenant_id, "summary": (results[0].get("summary") or {}).get("load")}
    clock.set_pinned(None)


def _contracts(db) -> dict:
    return {c.number: c for c in db.execute(select(Contract).where(Contract.number.like("KAC-%"))).scalars()}


# ---------------------------------------------------------------- the extract
def test_generator_is_deterministic_and_matches_the_committed_extract(tmp_path):
    manifest = erp_mock_contracts.generate(tmp_path / "KAC_CLM")
    committed = json.loads((erp_mock_contracts.OUT_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    assert {k: v["sha256"] for k, v in manifest["files"].items()} == {k: v["sha256"] for k, v in committed["files"].items()}
    extract = contract_load.read_extract(erp_mock_contracts.OUT_DIR)       # row counts and SHA-256 verified
    assert len(extract["tables"]["CLM_CONTRACT"]) == 60 and len(extract["tables"]["CLM_CLAUSE"]) > 1000
    with pytest.raises(contract_load.ExtractError):
        contract_load.read_extract(tmp_path / "nothing")


# ---------------------------------------------------------------- portfolio
def test_portfolio_counts_by_type_and_status(loaded):
    with tenant_tx(loaded["tenant_id"]) as db:
        contracts = _contracts(db)
        assert len(contracts) == 60
        assert Counter(c.type for c in contracts.values()) == {
            "MASTER_AGREEMENT": 14, "SCHEDULING_AGREEMENT": 6, "QUANTITY_CONTRACT": 8, "VALUE_CONTRACT": 6, "RATE_CARD": 8, "SOW": 8, "NDA": 10}
        # The finance pack loads this portfolio early (its rebate agreements need the master agreements) and a later test module can run the scheduled
        # renewal and expiry jobs on the shared database with the business clock pinned months ahead, so ACTIVE, EXPIRING and EXPIRED may have moved
        # on: the pack guarantees the lifecycle family in total and the statuses outside it exactly.
        status = Counter(c.status for c in contracts.values())
        assert {k: v for k, v in status.items() if k not in ("ACTIVE", "EXPIRING", "EXPIRED")} == {
            "TERMINATED": 1, "IN_NEGOTIATION": 2, "OUT_FOR_SIGNATURE": 1, "DRAFT": 1}
        assert status["ACTIVE"] + status["EXPIRING"] + status["EXPIRED"] == 55
        # the 40 SAP outline agreements are untouched next to them (still 40; their status may move on when another test module
        # has run the renewal and expiry jobs on the shared database, so only the lifecycle family is asserted)
        sap = db.execute(select(Contract).where(~Contract.number.like("KAC-%"))).scalars().all()
        assert len(sap) == 40 and {c.status for c in sap} <= {"ACTIVE", "EXPIRING", "EXPIRED"}
        # masters carry no lines or value; call-offs do
        assert all(c.target_value_minor == 0 for c in contracts.values() if c.type in ("MASTER_AGREEMENT", "NDA"))
        assert all(c.target_value_minor > 0 for c in contracts.values() if c.type not in ("MASTER_AGREEMENT", "NDA"))
        # suppliers are the KAC vendors of the SAP extract
        suppliers = {s.id: s for s in db.execute(select(Supplier)).scalars()}
        assert all(suppliers[c.supplier_id].code.isdigit() for c in contracts.values())
        assert {c.jurisdiction for c in contracts.values()} <= {"IN-TN", "IN-KA", "IN-MH", "IN-GJ", "IN-HR", "IN"}
    if loaded["summary"]:
        assert loaded["summary"]["byType"]["NDA"] == 10


def test_call_offs_sit_inside_their_master_agreement(loaded):
    with tenant_tx(loaded["tenant_id"]) as db:
        contracts = _contracts(db)
        by_id = {c.id: c for c in contracts.values()}
        children = [c for c in contracts.values() if c.framework_contract_id]
        assert Counter(c.type for c in children if c.type != "SOW")["SCHEDULING_AGREEMENT"] == 6
        assert len([c for c in children if c.type in ("SCHEDULING_AGREEMENT", "QUANTITY_CONTRACT", "VALUE_CONTRACT")]) == 20
        for child in children:
            master = by_id[child.framework_contract_id]
            assert master.type == "MASTER_AGREEMENT" and master.supplier_id == child.supplier_id
            assert master.valid_from <= child.valid_from and child.valid_to <= master.valid_to, child.number
        # a call-off has lines with the SAP materials and published prices; an index where the scheduling agreement carries one
        sa = contracts["KAC-SA-0001"]
        lines = db.execute(select(ContractLine).where(ContractLine.contract_id == sa.id)).scalars().all()
        assert lines and all(l.material_id for l in lines) and sa.index_ref["index"] == "LME_AL"
        # a price revision (variation amendment) gives the line two validity periods
        validity = db.execute(select(PriceValidity).where(PriceValidity.contract_line_id == lines[0].id).order_by(PriceValidity.valid_from)).scalars().all()
        assert len(validity) == 2 and validity[1].unit_price_minor > validity[0].unit_price_minor and validity[0].valid_to < validity[1].valid_from


# ---------------------------------------------------------------- clauses from the library
def test_every_clause_comes_from_the_library_with_standard_fallback_and_non_standard_positions(loaded):
    with tenant_tx(loaded["tenant_id"]) as db:
        playbook = rules.resolve(db, "CLM-PLAYBOOK")
        assert playbook.body["clauseLibrary"]["source"] == clause_library.SOURCE
        meta = clause_library.metadata(playbook.body)
        suppliers = {s.id: s.legal_name for s in db.execute(select(Supplier)).scalars()}
        positions = Counter()
        for number, c in _contracts(db).items():
            library = contract_svc._library(
                playbook.body, type=c.type, payment_terms=c.payment_terms, incoterms=c.incoterms, supplier_name=suppliers[c.supplier_id], index_ref=c.index_ref,
                tolerances={"over_pct": c.over_tolerance_pct, "under_pct": c.under_tolerance_pct}, jurisdiction=c.jurisdiction, category=c.category)
            clauses = db.execute(select(Clause).where(Clause.contract_id == c.id)).scalars().all()
            assert len(clauses) >= 11 and {x.code for x in clauses} <= set(library), (number, {x.code for x in clauses} - set(library))
            for clause in clauses:
                assert clause.standard_text == library[clause.code]["text"], (number, clause.code)
                positions[clause.position] += 1
                if clause.position == "STANDARD":
                    assert clause.text == clause.standard_text and clause.risk_score == 0
                elif clause.position == "FALLBACK":
                    assert clause.text in [f["text"] for f in meta[clause.code]["fallbackPositions"]] and clause.risk_score == 30
                else:
                    assert clause.text != clause.standard_text and clause.risk_score == 70
        assert positions["STANDARD"] > 1000 and positions["FALLBACK"] >= 10 and positions["NON_STANDARD"] >= 10
        # MSME payment rule, DPDP Act and arbitration are in the contracts of the master agreements
        ma = _contracts(db)["KAC-MA-0003"]
        texts = {x.code: x.text for x in db.execute(select(Clause).where(Clause.contract_id == ma.id)).scalars()}
        assert "section 15" in texts["PAYMENT"] and "Digital Personal Data Protection Act" in texts["DATA_PROTECTION"] and "Arbitration and Conciliation Act" in texts["DISPUTES"]
        assert {"LIABILITY", "INDEMNITY", "ANTI_BRIBERY", "AUDIT_RIGHTS", "FORCE_MAJEURE", "ESG_CONDUCT", "SUBCONTRACTING", "INSURANCE"} <= set(texts)


def test_a_risky_contract_shows_risk_weight_escalation_and_fallbacks_in_the_clause_review(loaded, client, login):
    h = login("contract.manager@kaveri-auto.example", "KAC")
    review = client.get("/v1/contracts/KAC-SA-0005/clause-review", headers=h)
    assert review.status_code == 200, review.text
    body = review.json()
    assert body["riskBand"] == "HIGH" and body["risk"] == 70 and body["approval"]["chain"] == ["LEGAL", "FINANCE_CONTROLLER", "CPO"]
    payment = next(c for c in body["clauses"] if c["clause"] == "PAYMENT")
    assert payment["position"] == "NON_STANDARD" and payment["deviation"] and payment["riskWeight"] == 8 and payment["escalationRole"] == "FINANCE_CONTROLLER"
    assert payment["suggestedPosition"] == "FALLBACK" and len(payment["fallbackPositions"]) == 2 and payment["fallback"] == "N45 minimum"
    liability = next(c for c in body["clauses"] if c["clause"] == "LIABILITY")
    assert liability["escalationRole"] == "LEGAL" and liability["riskWeight"] == 9


# ---------------------------------------------------------------- obligations, milestones, renewals
def test_obligations_and_milestones_are_a_mix_of_on_time_late_and_overdue(loaded):
    with tenant_tx(loaded["tenant_id"]) as db:
        tracker = contract_svc.obligations_tracker(db)
        kac = [i for i in tracker["items"] if i["contract"].startswith("KAC-")]
        assert len(kac) == len(contract_load.read_extract(erp_mock_contracts.OUT_DIR)["tables"]["CLM_OBLIGATION"])
        states = Counter(i["status"] for i in kac)
        assert states["OVERDUE"] >= 10 and states["COMPLETED"] >= 100 and states["DUE_SOON"] + states["OPEN"] > 0
        completed = [i for i in kac if i["status"] == "COMPLETED"]
        assert any(i["onTime"] for i in completed) and any(not i["onTime"] for i in completed)
        assert tracker["onTimePct"] is not None and Decimal(tracker["onTimePct"]) < 100
        # milestones of the statements of work, some overdue
        milestones = [i for i in kac if i["kind"] == "MILESTONE"]
        assert len(milestones) >= 20 and any(i["status"] == "OVERDUE" for i in milestones) and any(i["status"] == "COMPLETED" for i in milestones)
        # obligations after a termination are cancelled, and every DONE one carries evidence
        terminated = _contracts(db)["KAC-VC-0004"]
        rows = db.execute(select(Obligation).where(Obligation.contract_id == terminated.id)).scalars().all()
        assert any(o.status == "CANCELLED" for o in rows) or all(o.due_date <= terminated.terminated_at.date() for o in rows)
        assert all(o.completed_at and o.completion_note for o in db.execute(select(Obligation).where(Obligation.status == "DONE")).scalars())


def test_renewals_list_has_contracts_expiring_within_30_90_and_120_days(loaded):
    with tenant_tx(loaded["tenant_id"]) as db:
        rows = [r for r in contract_svc.renewals(db) if r["contract"].startswith("KAC-")]
        assert rows
        # the windows come from the contracts' own end dates (a contract the scheduler already moved to EXPIRED is no longer on the renewals list)
        ends = {c.number: (c.valid_to - TODAY).days for c in _contracts(db).values() if c.status in ("ACTIVE", "EXPIRING", "EXPIRED")}
        within = lambda days: {number for number, left in ends.items() if 0 <= left <= days}
        assert within(30) == {"KAC-NDA-0004", "KAC-RC-0005"}
        assert len(within(90)) == 7 and len(within(120)) == 9 and "KAC-SA-0002" not in within(120)   # 128 days: outside the notice window
        assert {r["contract"] for r in rows if r["expiringIn90"]} <= within(90)
        expiring = {r["contract"]: r for r in rows if r["status"] == "EXPIRING"}
        # a contract the scheduler moved to EXPIRING on a later, pinned clock may still be outside the notice window at this date: the renewal decision
        # is waiting for the ones inside it
        inside = {k: r for k, r in expiring.items() if r["daysToExpiry"] <= 120}
        assert all(r["noticeDue"] and r["renewalTask"] for r in inside.values())
        # expired and terminated contracts are not on the list
        assert not {"KAC-QC-0007", "KAC-RC-0008", "KAC-VC-0004"} & {r["contract"] for r in rows}
        # active contracts have the renewal and expiry timers, expiring ones the expiry timer only
        contracts = _contracts(db)
        timers = Counter((contracts_by_id(contracts)[t.object_id].status, t.kind) for t in db.execute(select(Timer).where(Timer.kind.in_(("CONTRACT_RENEWAL", "CONTRACT_EXPIRY")))).scalars()
                         if t.object_id in contracts_by_id(contracts))
        active, expiring_n = sum(1 for c in contracts.values() if c.status == "ACTIVE"), sum(1 for c in contracts.values() if c.status == "EXPIRING")
        assert timers[("ACTIVE", "CONTRACT_RENEWAL")] == active and timers[("ACTIVE", "CONTRACT_EXPIRY")] == active
        assert timers[("EXPIRING", "CONTRACT_EXPIRY")] == expiring_n    # whether an EXPIRING one still has its renewal timer depends on the clock the scheduler ran on


def contracts_by_id(contracts: dict) -> dict:
    return {c.id: c for c in contracts.values()}


# ---------------------------------------------------------------- negotiation, termination, amendments, rebates, signatures
def test_negotiation_with_supplier_redlines_and_a_terminated_contract(loaded):
    with tenant_tx(loaded["tenant_id"]) as db:
        contracts = _contracts(db)
        s1 = contracts["KAC-SOW-0001"]
        assert s1.status == "IN_NEGOTIATION"
        pending = contract_svc.pending_redlines(db, s1)
        assert sorted(pending) == ["IP", "LIABILITY", "PAYMENT"] and all(p["originalText"] and p["proposedText"] != p["originalText"] for p in pending.values())
        liability = db.execute(select(Clause).where(Clause.contract_id == s1.id, Clause.code == "LIABILITY")).scalar_one()
        assert liability.position == "NON_STANDARD" and liability.text == pending["LIABILITY"]["proposedText"]
        # the buyer cannot submit until the redlines are reviewed
        assert sorted(contract_svc.clause_review(db, s1)["pendingReview"]) == ["IP", "LIABILITY", "PAYMENT"]
        gone = contracts["KAC-VC-0004"]
        assert gone.status == "TERMINATED" and "provident fund" in gone.termination_reason and gone.terminated_at.astimezone(clock.IST).date() == date(2026, 9, 15)
        amendment = db.execute(select(ContractAmendment).where(ContractAmendment.contract_id == gone.id)).scalar_one()
        assert amendment.kind == "TERMINATION" and amendment.status == "EFFECTIVE" and amendment.changes == {"forCause": True}
        published = db.execute(select(PriceValidity).join(ContractLine, ContractLine.id == PriceValidity.contract_line_id).where(ContractLine.contract_id == gone.id)).scalars().all()
        assert published and not any(p.published for p in published)          # prices stopped with the termination


def test_amendment_history_rebates_and_signed_documents(loaded):
    with tenant_tx(loaded["tenant_id"]) as db:
        contracts = _contracts(db)
        amendments = db.execute(select(ContractAmendment).where(ContractAmendment.contract_id.in_([c.id for c in contracts.values()]))).scalars().all()
        assert Counter(a.kind for a in amendments) == {"TERMS": 3, "VARIATION": 3, "EXTENSION": 2, "TERMINATION": 1} and len(amendments) == 9
        assert Counter(a.status for a in amendments)["REJECTED"] == 1
        assert contracts["KAC-MA-0001"].version == 2 and contracts["KAC-SA-0003"].version == 3 and contracts["KAC-RC-0002"].version == 2     # a rejected amendment adds no version
        assert contracts["KAC-MA-0001"].payment_terms == "N45"
        # rebate agreements with tiers, through the real service
        agreements = db.execute(select(RebateAgreement).where(~RebateAgreement.title.like("MOCK%"))).scalars().all()   # the finance pack adds two MOCK agreements of its own
        assert len(agreements) == 6
        by_scope = Counter((a.scope, a.basis, a.tier_mode) for a in agreements)
        assert by_scope[("SUPPLIER", "VALUE", "RETROACTIVE")] == 2 and by_scope[("SUPPLIER", "VALUE", "SLAB")] == 2 and by_scope[("CONTRACT", "VOLUME", "RETROACTIVE")] == 1
        assert all(len(a.tiers) >= 2 and Decimal(a.tiers[-1]["ratePct"]) > Decimal(a.tiers[0]["ratePct"]) for a in agreements)
        # signed contracts: both parties, bound to the hash of the loaded text; the contract out for signature has the buyer's signature only
        for number in ("KAC-MA-0001", "KAC-QC-0007", "KAC-VC-0004", "KAC-NDA-0007"):
            c = contracts[number]
            signatures = db.execute(select(Signature).where(Signature.contract_id == c.id)).scalars().all()
            assert {s.party for s in signatures} == {"BUYER", "SUPPLIER"} and {s.document_hash for s in signatures} == {contract_svc._document_hash(db, c)}
            assert all(contract_svc.signature_provider(s.envelope_ref) == "MIGRATED" for s in signatures)
        assert [s.party for s in db.execute(select(Signature).where(Signature.contract_id == contracts["KAC-SOW-0002"].id)).scalars()] == ["BUYER"]
        assert not db.execute(select(Signature).where(Signature.contract_id == contracts["KAC-SOW-0001"].id)).first()


# ---------------------------------------------------------------- idempotency
def test_a_second_apply_writes_nothing(loaded):
    assert datasets.apply_pack("contracts_kac", PASSWORD)[0]["status"] == "ALREADY_LOADED"
    with tenant_tx(loaded["tenant_id"]) as db:
        before = db.execute(select(Contract.id)).scalars().all(), len(db.execute(select(Clause.id)).scalars().all()), len(db.execute(select(Obligation.id)).scalars().all())
    again = contract_load.load("KAC", None, when=at(TODAY, 9))                     # the loader itself is idempotent too
    assert again["loaded"] == 0 and again["existing"] == 60 and not again["rejects"]
    with tenant_tx(loaded["tenant_id"]) as db:
        after = db.execute(select(Contract.id)).scalars().all(), len(db.execute(select(Clause.id)).scalars().all()), len(db.execute(select(Obligation.id)).scalars().all())
        assert len(after[0]) == len(before[0]) and after[1:] == before[1:]
        assert len(db.execute(select(RebateAgreement.id).where(~RebateAgreement.title.like("MOCK%"))).scalars().all()) == 6
