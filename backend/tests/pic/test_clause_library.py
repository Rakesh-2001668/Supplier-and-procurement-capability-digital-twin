"""The clause library (ILLUSTRATIVE SAMPLE, seed/clause_library.py): content, file formats, the validator, how existing tenants get it
(reference.ensure_extensions: a new effective-dated version, the tenant's own entries win), how a client's own file replaces it
(tools/clause_library_load) and that drafts, the category overlays and the governing-law variants use it."""
import json
from datetime import date

import pytest
from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import AppUser, RuleSet, Supplier
from app.pic.platform import clock, rules
from app.pic.platform.auth import hash_password
from app.pic.seed import clause_library as lib
from app.pic.seed import reference
from app.pic.seed.datasets import _tenant_kit as kit
from app.pic.services import contract as contract_svc
from app.pic.tools import clause_library_load

from .conftest import PASSWORD

CODE, DOMAIN = "CLB1", "clb1.example"
USERS = [("cm", "Chandra Contracts", ["CONTRACT_MANAGER"], {}), ("admin", "Admin Anil", ["TENANT_ADMIN"], {})]


@pytest.fixture(scope="module")
def tenant(database):
    sc = kit.setup_tenant(CODE, "Clause Library Industries Pvt Ltd", "GENERAL", company=("1000", "Clause Library Industries Pvt Ltd", "29AAKCD4821M1Z7"),
                          plants=[("P100", "Main plant", "29")], cost_objects=[("COST_CENTER", "6100", "Test cost centre")], holidays=[], domain=DOMAIN,
                          role_user={"CONTRACT_MANAGER": "cm"})
    kit.create_users(sc, USERS, PASSWORD)
    kit.rule_version(sc, "MFA", "2026.1-CLB", date(2026, 4, 1), {"enforce": False}, "no MFA challenge for the API tests")
    with tenant_tx(sc.tenant_id) as s:
        s.add(Supplier(tenant_id=sc.tenant_id, code="CLB-SUP", legal_name="Library Test Pvt Ltd", status="QUALIFIED", country="IN", state_code="29", payment_terms="N30"))
    return sc


def _draft(client, login, **over):
    today = clock.today()
    body = {"type": "MASTER_AGREEMENT", "title": "Library test", "supplier": "CLB-SUP", "company_code": "1000", "valid_from": today.isoformat(),
            "valid_to": date(today.year + 3, today.month, 1).isoformat(), "payment_terms": "N45", **over}
    r = client.post("/v1/contracts", json=body, headers=login(f"cm@{DOMAIN}", CODE))
    assert r.status_code == 201, r.text
    return client.get(f"/v1/contracts/{r.json()['number']}", headers=login(f"cm@{DOMAIN}", CODE)).json()


# ---------------------------------------------------------------- content
def test_the_sample_library_is_complete_and_labelled():
    doc = lib.validate(lib.library())
    assert "ILLUSTRATIVE SAMPLE" in lib.__doc__ and "NOT LEGAL ADVICE" in lib.__doc__ and "REPLACE WITH LEGAL-APPROVED TEXT" in lib.__doc__
    assert doc["source"] == "ILLUSTRATIVE_SAMPLE" and "NOT LEGAL ADVICE" in doc["disclaimer"]
    summary = lib.summary(doc)
    assert summary["clauses"] >= 30 and summary["overlays"] == 8 and summary["jurisdictions"] == 7 and summary["fallbacks"] >= 70
    assert all(n >= 8 for n in summary["clausesPerType"].values()) and set(summary["clausesPerType"]) == set(lib.CONTRACT_TYPES)
    everything = [*doc["clauses"], *[c for o in doc["overlays"] for c in o["clauses"]]]
    assert all(1 <= len(c["fallbacks"]) <= 2 and 1 <= c["riskWeight"] <= 10 and c["escalationRole"] in lib.ESCALATION_ROLES for c in everything)
    codes = {c["code"] for c in doc["clauses"]}
    assert {"PAYMENT", "LIABILITY", "INDEMNITY", "IP", "CONFIDENTIALITY", "TERMINATION", "TERMINATION_CAUSE", "FORCE_MAJEURE", "WARRANTY", "PRICE_VARIATION", "QUALITY", "PPAP",
            "DELIVERY", "LIQUIDATED_DAMAGES", "AUDIT_RIGHTS", "DATA_PROTECTION", "ANTI_BRIBERY", "ESG_CONDUCT", "SUBCONTRACTING", "INSURANCE", "DISPUTE_RESOLUTION"} <= codes
    payment = next(c for c in doc["clauses"] if c["code"] == "PAYMENT")["text"]
    assert "45 days" in payment and "section 15" in payment and "Micro, Small and Medium Enterprises Development Act, 2006" in payment
    assert "Digital Personal Data Protection Act, 2023" in next(c for c in doc["clauses"] if c["code"] == "DATA_PROTECTION")["text"]
    assert "Arbitration and Conciliation Act, 1996" in next(c for c in doc["clauses"] if c["code"] == "DISPUTE_RESOLUTION")["text"]
    assert {c["name"] for c in doc["overlays"]} == {"CASTINGS_FORGINGS", "ELECTRONICS", "IT_SERVICES_SOFTWARE", "LOGISTICS_FREIGHT", "CONSTRUCTION_WORKS", "HEALTHCARE_SUPPLIES",
                                                    "PROFESSIONAL_SERVICES", "MRO"}
    assert set(doc["jurisdictions"]) == {"IN-TN", "IN-MH", "IN-KA", "IN-GJ", "GB", "SG", "US-DE"}
    # every jurisdiction fills the jurisdiction clauses of the service
    for code in doc["jurisdictions"]:
        variant = contract_svc.jurisdiction_clauses({"jurisdictions": doc["jurisdictions"]}, code)
        assert [v["code"] for v in variant] == ["GOVERNING_LAW", "DISPUTES", "STAMP_DUTY", "DATA_PROTECTION"]
    assert "Delaware" in contract_svc.jurisdiction_clauses({"jurisdictions": doc["jurisdictions"]}, "US-DE")[0]["text"]


def test_csv_and_json_files_round_trip_and_the_validator_names_every_problem(tmp_path):
    doc = lib.library()
    (tmp_path / "lib.csv").write_text(lib.to_csv(doc), encoding="utf-8")
    (tmp_path / "lib.json").write_text(json.dumps(doc), encoding="utf-8")
    from_csv, from_json = lib.read_file(tmp_path / "lib.csv"), lib.read_file(tmp_path / "lib.json")
    assert from_csv["clauses"] == from_json["clauses"] == doc["clauses"]
    assert [o["clauses"] for o in from_csv["overlays"]] == [o["clauses"] for o in doc["overlays"]]
    assert {k: {x: v[x] for x in lib.JURISDICTION_KEYS} for k, v in from_csv["jurisdictions"].items()} == {k: {x: v[x] for x in lib.JURISDICTION_KEYS} for k, v in doc["jurisdictions"].items()}
    assert lib.playbook_patch(from_csv)["fallbacks"] == lib.playbook_patch(doc)["fallbacks"]
    bad = lib.library()
    bad["clauses"][0].update(riskWeight=11, types=["MASTER_AGREEMENT", "LEASE"], escalationRole="JANITOR", text="Pay {nobody} now {")
    bad["clauses"][1]["fallbacks"] = [{"label": "a", "text": "x"}] * 3
    bad["jurisdictions"]["IN-ZZ"] = {"name": "Nowhere"}
    with pytest.raises(lib.LibraryError) as error:
        lib.validate(bad)
    message = str(error.value)
    assert all(part in message for part in ("riskWeight", "types", "escalationRole", "placeholder", "at most two fallback", "jurisdiction IN-ZZ"))
    (tmp_path / "bad.csv").write_text("kind,code\nWHAT,X\n", encoding="utf-8")
    with pytest.raises(lib.LibraryError):
        lib.read_file(tmp_path / "bad.csv")
    assert clause_library_load.main(["--file", str(tmp_path / "lib.csv"), "--validate-only"]) == 0
    assert clause_library_load.main(["--file", str(tmp_path / "bad.csv"), "--validate-only"]) == 1


def test_the_bootstrap_playbook_carries_the_library_without_touching_the_built_in_templates():
    body = reference.RULE_SETS["CLM-PLAYBOOK"][0]
    assert body["clauseLibrary"]["source"] == "ILLUSTRATIVE_SAMPLE" and body["clauseLibrary"]["precedence"] == "LIBRARY"
    assert set(body["templates"]) == {"SCHEDULING_AGREEMENT", "VALUE_CONTRACT", "QUANTITY_CONTRACT"}      # unchanged
    assert body["fallbacks"]["LIABILITY"] == "Cap at 50% of annual value" and body["fallbacks"]["PAYMENT"] == "N45 minimum"       # the existing fallbacks stay
    assert "FORGINGS" in body["categoryClauses"] and "IT-SERVICES" in body["categoryClauses"] and body["jurisdictions"]["US-DE"]["name"] == "Delaware, USA"


# ---------------------------------------------------------------- drafting
def test_drafts_take_the_library_overlay_and_governing_law_variant(client, login, tenant):
    plain = _draft(client, login)
    codes = {c["code"]: c for c in plain["clauses"]}
    assert {"PAYMENT", "LIABILITY", "INDEMNITY", "TERMINATION_CAUSE", "ANTI_BRIBERY", "DATA_PROTECTION", "DISPUTE_RESOLUTION"} <= set(codes) and "GOVERNING_LAW" not in codes
    assert "Payment N45 from receipt" in codes["PAYMENT"]["text"] and "section 15" in codes["PAYMENT"]["text"]
    assert all(c["position"] == "STANDARD" and c["standard_text"] == c["text"] and c["risk_score"] == 0 for c in plain["clauses"])
    castings = _draft(client, login, type="MASTER_AGREEMENT", category="FORGINGS", jurisdiction="US-DE")
    texts = {c["code"]: c["text"] for c in castings["clauses"]}
    assert {"TOOLING_OWNERSHIP", "CASTING_INTEGRITY"} <= set(texts) and "Delaware" in texts["GOVERNING_LAW"]
    nda = _draft(client, login, type="NDA", jurisdiction="GB")
    assert {c["code"] for c in nda["clauses"]} >= {"DEFINITION", "USE", "TERM", "PERMITTED_DISCLOSURE", "RETURN", "NO_LICENCE", "REMEDIES", "GOVERNING_LAW"}
    assert "PAYMENT" not in {c["code"] for c in nda["clauses"]}
    review = client.get(f"/v1/contracts/{plain['number']}/clause-review", headers=login(f"cm@{DOMAIN}", CODE)).json()
    liability = next(c for c in review["clauses"] if c["clause"] == "LIABILITY")
    assert liability["riskWeight"] == 9 and liability["escalationRole"] == "LEGAL" and len(liability["fallbackPositions"]) == 2 and liability["fallback"] == "Cap at 50% of annual value"
    assert review["risk"] == 0
    templates = client.get("/v1/contract-templates", headers=login(f"cm@{DOMAIN}", CODE)).json()
    assert templates["library"]["source"] == "ILLUSTRATIVE_SAMPLE" and len(templates["libraryClauses"]["SOW"]) >= 20 and "US-DE" in {j["code"] for j in templates["jurisdictions"]}


# ---------------------------------------------------------------- tenants that exist already, and replacement by the client's file
def test_an_existing_tenant_gets_a_new_version_and_keeps_its_own_entries(tenant):
    with tenant_tx(tenant.tenant_id) as s:
        current = rules.resolve(s, "CLM-PLAYBOOK")
        old_body = {k: v for k, v in current.body.items() if k not in ("clauseLibrary", "categoryClauses", "jurisdictions", "fallbacks")}
        old_body["categoryClauses"] = {"CUSTOM": [{"code": "CUSTOM_CLAUSE", "title": "Custom", "text": "Tenant wording."}]}
        old_body["fallbacks"] = {"LIABILITY": "Tenant fallback"}
        s.add(RuleSet(tenant_id=tenant.tenant_id, key="CLM-PLAYBOOK", version="2025.9-OLD", effective_from=date(2026, 4, 2), body=old_body, description="a tenant bootstrapped by an earlier release"))
    added = reference.ensure_extensions(tenant.tenant_id)
    assert "rule set CLM-PLAYBOOK@2026.3" in added
    with tenant_tx(tenant.tenant_id) as s:
        versions = {r.version: r for r in s.execute(select(RuleSet).where(RuleSet.key == "CLM-PLAYBOOK")).scalars()}
        assert versions["2025.9-OLD"].body.get("clauseLibrary") is None                            # an existing version is never edited
        new = versions["2026.3"]
        assert new.effective_from == clock.today() and new.body["clauseLibrary"]["source"] == "ILLUSTRATIVE_SAMPLE"
        assert new.body["fallbacks"]["LIABILITY"] == "Tenant fallback" and "FORGINGS" in new.body["categoryClauses"] and "CUSTOM" in new.body["categoryClauses"]
        assert rules.resolve(s, "CLM-PLAYBOOK").version == "2026.3"
    assert not [a for a in reference.ensure_extensions(tenant.tenant_id) if "CLM-PLAYBOOK" in a]       # idempotent


def test_a_client_file_replaces_the_sample_without_code_changes(client, login, tenant, tmp_path):
    doc = lib.library()
    payment = next(c for c in doc["clauses"] if c["code"] == "PAYMENT")
    payment.update(text="Client-approved wording: payment {terms} from receipt of a correct invoice.", riskWeight=10)
    doc["source"], doc["disclaimer"] = "CLIENT_LEGAL_SIGNED_OFF", ""
    path = tmp_path / "client.csv"
    path.write_text(lib.to_csv(doc), encoding="utf-8")
    result = clause_library_load.apply(CODE, lib.read_file(path), label="client.csv")
    assert result["version"].startswith("LIB-") and result["summary"]["clauses"] == len(doc["clauses"])
    with tenant_tx(tenant.tenant_id) as s:
        rule = rules.resolve(s, "CLM-PLAYBOOK")
        assert rule.version == result["version"] and rule.body["clauseLibrary"]["source"] == "FILE" and "templates" in rule.body        # the rest of the playbook stays
    drafted = _draft(client, login)
    texts = {c["code"]: c["text"] for c in drafted["clauses"]}
    assert texts["PAYMENT"].startswith("Client-approved wording: payment N45")
