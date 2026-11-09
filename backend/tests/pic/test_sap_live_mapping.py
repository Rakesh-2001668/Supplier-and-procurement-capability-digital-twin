"""Live SAP S/4HANA mapping of OUTLINE_AGREEMENT, PAYMENT_REVERSAL and SCF_FINANCING (platform/sap_mapping.py, rules in platform/sap_defaults.py):
golden request bodies for every contract type, a change and a close, the reversal and the supply-chain-finance journal entry (OData and IDoc);
the skip of legal documents; rule overrides and rule validation; the sandbox simulator validating the same bodies against the mock SAP
customizing (backend/data/erp_mock/SAP_CONFIG, platform/sap_customizing.py); query-before-retry for the new types; and round trips against the
loopback SAP mock (tests/pic/sap_mock.py: a local HTTP server, no network, no secrets).

VALIDATED AGAINST THE MOCK ONLY: field names are those of the released APIs as far as known; the assumptions are listed in
docs/PIC_SAP_Document_Types.md and must be confirmed in the client's sandbox.
"""
import json
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.pic.models import AuditEvent, Contract, ContractLine, ErpDocument, IntegrationMessage, Invoice, Material, Payment, PostingPeriod, PriceValidity, \
    PurchasingOrg, RuleSet, Supplier
from app.pic.platform import connectors, integration, sap_customizing as cz, sap_defaults as sd, sap_mapping as sm, sap_odata
from app.pic.services import contract as contract_svc
from app.pic.services.common import principal
from app.pic.tools import ai_eval

from .sap_mock import SapMock

DAY = date(2027, 3, 31)
CTX = {"version": 2, "company": "1000", "vendor": "200081", "reference": "1000|OA|QC-6101|v1|abc", "purch_org": "PO10", "purch_group": "G01",
       "today": date(2027, 4, 1), "payment_terms": "Z045"}
START, END = "/Date(1806537600000)/", "/Date(1838073600000)/"          # 2027-04-01 and 2028-03-31 (OData v2 JSON dates, UTC midnight)


def cfg(**over) -> dict:
    return {**sd.OUTLINE_AGREEMENT, "textItemMaterialGroup": "SERVICES", **over}


def contract_payload(kind="QUANTITY_CONTRACT", lines=None, **over) -> dict:
    lines = lines if lines is not None else [
        {"line": 10, "material": "FK-M8-50", "description": "Fastener kit M8 x 50 zinc flake", "plant": "P100", "uom": "EA", "targetQty": "20000.000",
         "priceMinor": 1250}]
    return {"contract": "QC-6101", "version": 1, "type": kind, "supplier": "KD002", "companyCode": "1000", "currency": "INR", "validFrom": "2027-04-01",
            "validTo": "2028-03-31", "paymentTerms": "N45", "incoterms": "FCA Coimbatore", "targetValueMinor": 25_000_000, "lines": lines, **over}


TEXT_LINE = {"line": 10, "material": None, "description": "Tool polishing, per hour", "plant": "P100", "uom": "H", "targetQty": "100.000", "priceMinor": 300000}


def plan_of(p, api="CONTRACT", c=None, **kw):
    return sm.outline_agreement(p, CTX, c or cfg(), api, p["lines"], **kw)


# ================================================================ golden bodies: create
def test_quantity_contract_is_an_MK_purchase_contract_golden():
    plan = plan_of(contract_payload())
    assert (plan.api, plan.action, plan.doc_type, plan.service, plan.header_set, plan.number_field) == (
        "CONTRACT", "CREATE", "MK", "API_PURCHASECONTRACT_PROCESS_SRV", "A_PurchaseContract", "PurchaseContract")
    [op] = plan.ops
    assert (op.method, op.path) == ("POST", "A_PurchaseContract") and repr(op) == "Op(POST A_PurchaseContract)"
    assert op.body == {
        "PurchaseContractType": "MK", "CompanyCode": "1000", "PurchasingOrganization": "PO10", "PurchasingGroup": "G01", "Supplier": "200081",
        "DocumentCurrency": "INR", "ValidityStartDate": START, "ValidityEndDate": END, "PaymentTerms": "Z045", "IncotermsClassification": "FCA",
        "IncotermsLocation1": "Coimbatore", "CorrespncExternalReference": "1000|OA|QC-6", "PurchaseContractTargetAmount": "250000.00",
        "to_PurchaseContractItem": {"results": [{
            "PurchaseContractItem": "10", "PurchaseContractItemText": "Fastener kit M8 x 50 zinc flake", "Material": "FK-M8-50", "Plant": "P100",
            "TargetQuantity": "20000.000", "OrderQuantityUnit": "EA", "ContractNetPriceAmount": "12.50", "NetPriceQuantity": "1"}]}}
    assert cz.check_outline(plan, "QUANTITY_CONTRACT") == []


@pytest.mark.parametrize("kind", ["VALUE_CONTRACT", "RATE_CARD", "SOW"])
def test_value_contract_rate_card_and_sow_are_WK_value_contracts_with_text_items(kind):
    plan = plan_of(contract_payload(kind, [TEXT_LINE], targetValueMinor=30_000_000))
    body = plan.ops[0].body
    assert plan.doc_type == "WK" and body["PurchaseContractType"] == "WK" and body["PurchaseContractTargetAmount"] == "300000.00"
    assert body["to_PurchaseContractItem"]["results"] == [{
        "PurchaseContractItem": "10", "PurchaseContractItemText": "Tool polishing, per hour", "Plant": "P100", "TargetQuantity": "100.000",
        "OrderQuantityUnit": "H", "ContractNetPriceAmount": "3000.00", "NetPriceQuantity": "1", "MaterialGroup": "SERVICES", "AccountAssignmentCategory": "U"}]
    assert cz.check_outline(plan, kind) == []


def test_service_item_category_is_sent_for_the_service_types_only_when_configured():
    c = cfg(serviceItemCategory="D")
    sow = plan_of(contract_payload("SOW", [TEXT_LINE]), c=c).ops[0].body["to_PurchaseContractItem"]["results"][0]
    value = plan_of(contract_payload("VALUE_CONTRACT", [TEXT_LINE]), c=c).ops[0].body["to_PurchaseContractItem"]["results"][0]
    assert sow["PurchasingDocumentItemCategory"] == "D" and "PurchasingDocumentItemCategory" not in value


def test_scheduling_agreement_is_an_LP_on_the_scheduling_agreement_api_golden():
    p = contract_payload("SCHEDULING_AGREEMENT", [{"line": 10, "material": "DC-330", "description": "Die-cast housing DC-330", "plant": "P100", "uom": "EA",
                                                   "targetQty": "24000", "priceMinor": 41800}], contract="SA-5521", targetValueMinor=0, incoterms=None)
    plan = plan_of(p, "SCHEDULING_AGREEMENT")
    assert (plan.service, plan.header_set, plan.number_field, plan.doc_type) == ("API_SCHED_AGRMT_PROCESS_SRV", "A_SchAgrmtHeader", "SchedulingAgreement", "LP")
    assert plan.ops[0].body == {
        "PurchasingDocumentType": "LP", "CompanyCode": "1000", "PurchasingOrganization": "PO10", "PurchasingGroup": "G01", "Supplier": "200081",
        "DocumentCurrency": "INR", "ValidityStartDate": START, "ValidityEndDate": END, "PaymentTerms": "Z045", "CorrespncExternalReference": "1000|OA|QC-6",
        "to_SchAgrmtItem": {"results": [{"SchedulingAgreementItem": "10", "PurchasingDocumentItemText": "Die-cast housing DC-330", "Material": "DC-330",
                                         "Plant": "P100", "TargetQuantity": "24000.000", "OrderQuantityUnit": "EA", "NetPriceAmount": "418.00",
                                         "NetPriceQuantity": "1"}]}}
    assert cz.check_outline(plan, "SCHEDULING_AGREEMENT") == []


def test_odata_v4_sends_plain_lists_and_iso_dates():
    plan = sm.outline_agreement(contract_payload(), {**CTX, "version": 4}, cfg(), "CONTRACT", contract_payload()["lines"])
    body = plan.ops[0].body
    assert body["ValidityStartDate"] == "2027-04-01" and isinstance(body["to_PurchaseContractItem"], list)


def test_a_contract_type_without_document_type_cannot_be_mapped():
    with pytest.raises(ValueError, match="no SAP document type"):
        plan_of(contract_payload("NDA", []))


# ================================================================ golden bodies: change and close
def test_change_patches_the_items_sap_has_posts_the_new_ones_and_writes_the_reference_last():
    lines = [{**contract_payload()["lines"][0], "targetQty": "25000"}, {**TEXT_LINE, "line": 20}]
    plan = plan_of(contract_payload(lines=lines, version=2), number="4600000101", existing_items={"10"})
    assert plan.action == "CHANGE" and plan.number == "4600000101"
    assert [(o.method, o.path) for o in plan.ops] == [
        ("PATCH", "A_PurchaseContractItem(PurchaseContract='4600000101',PurchaseContractItem='10')"),
        ("POST", "A_PurchaseContract('4600000101')/to_PurchaseContractItem"),
        ("PATCH", "A_PurchaseContract('4600000101')")]
    assert plan.ops[0].body == {"PurchaseContractItemText": "Fastener kit M8 x 50 zinc flake", "TargetQuantity": "25000.000", "OrderQuantityUnit": "EA",
                                "ContractNetPriceAmount": "12.50", "NetPriceQuantity": "1"}
    assert plan.ops[1].body["PurchaseContract"] == "4600000101" and plan.ops[1].body["MaterialGroup"] == "SERVICES"
    assert plan.ops[2].body == {"ValidityEndDate": END, "PaymentTerms": "Z045", "IncotermsClassification": "FCA", "IncotermsLocation1": "Coimbatore",
                                "PurchaseContractTargetAmount": "250000.00", "CorrespncExternalReference": "1000|OA|QC-6"}
    assert cz.check_outline(plan, "QUANTITY_CONTRACT") == []


def test_close_sets_the_validity_end_and_the_reference_only():
    plan = plan_of(contract_payload(action="CLOSE", closeReason="TERMINATED", validTo="2027-09-30", lines=[]), number="4600000101")
    assert plan.action == "CLOSE" and [(o.method, o.path, o.body) for o in plan.ops] == [
        ("PATCH", "A_PurchaseContract('4600000101')", {"ValidityEndDate": "/Date(1822262400000)/", "CorrespncExternalReference": "1000|OA|QC-6"})]
    assert cz.check_outline(plan, "QUANTITY_CONTRACT") == []
    with pytest.raises(ValueError, match="no SAP number to close"):
        plan_of(contract_payload(action="CLOSE", lines=[]))


# ================================================================ skip of legal documents, rule resolution helpers
def test_master_agreements_and_ndas_are_skipped_not_errors_and_the_api_follows_the_document_category():
    config = sd.Config(sd.OUTLINE_KEY, "SAP-OUTLINE-AGREEMENT@test", cfg())
    for kind in ("MASTER_AGREEMENT", "NDA"):
        assert "legal document that is not sent" in sd.skip_reason(config, kind) and sd.api_of(config, kind) is None
    assert sd.skip_reason(config, "QUANTITY_CONTRACT") is None and sd.api_of(config, "QUANTITY_CONTRACT") == "CONTRACT"
    assert sd.api_of(config, "SCHEDULING_AGREEMENT") == "SCHEDULING_AGREEMENT"
    trimmed = sd.Config(sd.OUTLINE_KEY, "x@1", cfg(documentTypes={"SCHEDULING_AGREEMENT": "LPA"}, notSent=["MASTER_AGREEMENT", "NDA", "SOW"]))
    assert "no SAP document type for VALUE_CONTRACT" in sd.skip_reason(trimmed, "VALUE_CONTRACT") and sd.api_of(trimmed, "SCHEDULING_AGREEMENT") == "SCHEDULING_AGREEMENT"
    stray = sd.Config(sd.OUTLINE_KEY, "x@2", cfg(documentTypes={**sd.OUTLINE_AGREEMENT["documentTypes"], "SOW": "ZSOW"}))
    assert sd.api_of(stray, "SOW") is None and config["documentTypes"]["SOW"] == "WK"


# ================================================================ rule validation (POST /v1/admin/rules)
def test_the_default_bodies_and_the_D21_bodies_are_valid():
    for key, body in sd.DEFAULTS.items():
        assert sd.validate(key, body) == [], key
    assert sd.validate("DMN-01", {"anything": 1}) == [] and sd.validate(sd.OUTLINE_KEY, []) == ["the body must be an object"]


def test_outline_rule_validation_explains_each_problem():
    errors = sd.validate(sd.OUTLINE_KEY, {"documentTypes": {"QUANTITY_CONTRACT": "LP", "SCHEDULING_AGREEMENT": "MK", "NDA": "WK", "SOW": "TOOLONG", "X": "MK"},
                                          "contractTypes": ["MK", "WK", "LP"], "notSent": ["NDA", "BOGUS"], "serviceItems": ["NDA"],
                                          "purchasingOrg": "TOO-LONG", "closeOnRenewal": "yes", "colour": 1})
    text = " | ".join(errors)
    for expected in ("unknown key(s) colour", "cannot be both a contract type and a scheduling agreement type", "notSent must be a list",
                     "X is not a PIC contract type", "SOW must be an SAP document type", "serviceItems must be a list",
                     "purchasingOrg must be an SAP code of at most 4", "closeOnRenewal must be true or false"):
        assert expected in text, expected
    errors = sd.validate(sd.OUTLINE_KEY, {"documentTypes": {"QUANTITY_CONTRACT": "LP", "SCHEDULING_AGREEMENT": "MK", "NDA": "WK"}})
    assert any("SCHEDULING_AGREEMENT is MK, which is not in schedulingAgreementTypes" in e for e in errors)
    assert any("QUANTITY_CONTRACT is LP, which is not in contractTypes" in e for e in errors)
    assert any("NDA is listed in notSent" in e for e in errors)
    assert any("no SAP document type for VALUE_CONTRACT, RATE_CARD, SOW" in e for e in errors)
    assert sd.validate(sd.OUTLINE_KEY, {"contractTypes": "MK", "documentTypes": []})[:2] == [
        "contractTypes must be a list of SAP document types (at most 4 characters each)", "documentTypes must map PIC contract types to SAP document types"]


def test_reversal_and_scf_rule_validation():
    assert sd.validate(sd.REVERSAL_KEY, {"reversalReason": "1234", "postingDate": "TODAY", "closedPeriodReason": 2, "resetClearing": 1}) == [
        "reversalReason must be an SAP reversal reason (2 characters, e.g. 01)", "postingDate must be ORIGINAL or RETURN_DATE",
        "closedPeriodReason must be an SAP code of at most 2 characters, or null", "resetClearing must be true or false"]
    assert sd.validate(sd.SCF_KEY, {"documentType": "", "postingKeys": {"supplierDebit": "21"}, "financiers": []}) == [
        "documentType must be an SAP FI document type (2 characters, e.g. KA)",
        "postingKeys must give supplierDebit, financierCredit and glCredit as two-digit SAP posting keys",
        "financiers must map PIC financier codes to {businessPartner | glAccount, paymentMethod}"]
    errors = sd.validate(sd.SCF_KEY, {"financiers": {"A": "x", "B": {}, "C": {"businessPartner": "12345678901", "paymentMethod": "RR", "fee": 1},
                                                     "D": {"businessPartner": "1", "glAccount": "2"}, "E": {"glAccount": "21600000000"}}})
    assert errors == ["financiers.A must be an object", "financiers.B needs exactly one of businessPartner (credit the financier as a vendor) or glAccount",
                      "financiers.C: unknown key(s) fee", "financiers.C.businessPartner must be an SAP business partner number (at most 10 characters)",
                      "financiers.C.paymentMethod must be one SAP payment method character, or null",
                      "financiers.D needs exactly one of businessPartner (credit the financier as a vendor) or glAccount",
                      "financiers.E.glAccount must be an SAP G/L account (at most 10 characters)"]


def test_the_admin_api_refuses_an_invalid_sap_rule_and_accepts_a_valid_one(client, login):
    admin = login("admin")
    bad = client.post("/v1/admin/rules", headers=admin, json={"key": sd.REVERSAL_KEY, "version": "T-SAP-BAD", "effective_from": "2026-04-01",
                                                               "company_code": "9999", "body": {"postingDate": "TOMORROW"}})
    assert bad.status_code == 422 and bad.json()["code"] == "RULE_INVALID" and "postingDate must be ORIGINAL or RETURN_DATE" in bad.text
    unused_day = date(2090, 1, 1) + timedelta(days=time.time_ns() // 1000 % 20000)     # committed: a fresh scope date on a kept database
    good = client.post("/v1/admin/rules", headers=admin, json={"key": sd.REVERSAL_KEY, "version": f"T-SAP-{uuid.uuid4().hex[:6]}",
                                                                "effective_from": unused_day.isoformat(), "company_code": "9999",
                                                                "body": {"reversalReason": "02", "postingDate": "RETURN_DATE"}})
    assert good.status_code == 201, good.text


# ================================================================ payment reversal
def test_reversal_terms_follow_the_rule_and_the_closed_period():
    original, returned = date(2027, 1, 10), date(2027, 3, 5)
    assert sm.reversal_terms(sd.PAYMENT_REVERSAL, original, returned, False) == ("01", original)
    assert sm.reversal_terms(sd.PAYMENT_REVERSAL, original, returned, True) == ("02", returned)
    assert sm.reversal_terms({**sd.PAYMENT_REVERSAL, "reversalReason": "02", "postingDate": "RETURN_DATE"}, original, returned, False) == ("02", returned)
    assert sm.reversal_terms({**sd.PAYMENT_REVERSAL, "closedPeriodReason": None}, original, returned, True) == ("01", original)


def reversal_payload(**over):
    return {"payment": "PAY-880001", "clearingDocument": "1500002210", "amountMinor": 2_500_000, "companyCode": "1000", "reason": "Account closed", **over}


def test_payment_reversal_golden_and_the_customizing_check():
    ctx = {**CTX, "reference": "PAYREV|PAY-880001", "payment_service": "ZAPI_VENDOR_PAYMENT_SRV"}
    spec = sm.payment_reversal(reversal_payload(), ctx, sd.PAYMENT_REVERSAL, {"fiscalYear": "2026", "reason": "01", "postingDate": date(2027, 1, 10)})
    assert (spec.service, spec.entity_set, spec.reference_field, spec.reference, spec.number_field) == (
        "ZAPI_VENDOR_PAYMENT_SRV", "A_VendorPaymentReversal", "DocumentHeaderText", "PAYREV|PAY-880001", "ReverseDocument")
    assert spec.body == {"CompanyCode": "1000", "AccountingDocument": "1500002210", "FiscalYear": "2026", "ReversalReason": "01",
                         "PostingDate": "/Date(1799539200000)/", "ResetClearing": True, "DocumentHeaderText": "PAYREV|PAY-880001",
                         "PaymentReference": "PAY-880001", "ReversalText": "Account closed"}
    assert cz.check_reversal(spec.body, date(2027, 1, 10)) == []
    # reason 01 does not allow an alternative posting date; 02 does; an unknown reason is refused
    moved = {**spec.body, "PostingDate": "/Date(1804204800000)/"}
    assert "does not allow an alternative posting date" in cz.check_reversal(moved, date(2027, 1, 10))[0]
    assert cz.check_reversal({**moved, "ReversalReason": "02"}, date(2027, 1, 10)) == []
    assert "reversal reason 09 is not in the customizing" in cz.check_reversal({**spec.body, "ReversalReason": "09"}, None)[0]
    assert cz.check_reversal({"FiscalYear": "26"}, None)[-1] == "reversal: FiscalYear must have four digits"
    with pytest.raises(ValueError, match="no clearing document"):
        sm.payment_reversal(reversal_payload(clearingDocument=None), ctx, sd.PAYMENT_REVERSAL, {"fiscalYear": "2026", "reason": "01", "postingDate": DAY})


# ================================================================ supply-chain finance
def scf_payload(**over):
    return {"invoice": "KD/26-27/0412", "invoiceErp": "5100004425", "supplier": "KD002", "companyCode": "1000", "grossMinor": 59_000_000,
            "maturity": "2027-05-15", "financier": "PROGRAMME", "offer": str(uuid.UUID(int=1)), **over}


SCF_CFG = {**sd.SCF_FINANCING, "financiers": {"PROGRAMME": {"businessPartner": "9800001", "paymentMethod": "R"}, "BANKGL": {"glAccount": "21600000"}}}


def test_scf_journal_entry_moves_the_payable_to_the_financier_golden():
    ctx = {**CTX, "reference": "SCF|AXN|1000|KD002|0412", "currency": "INR", "journal_service": "ZAPI_JOURNAL_ENTRY_SRV"}
    spec = sm.scf_journal_entry(scf_payload(), ctx, SCF_CFG, sm.scf_financier(SCF_CFG, "PROGRAMME"))
    assert (spec.service, spec.entity_set, spec.reference_field, spec.number_field) == ("ZAPI_JOURNAL_ENTRY_SRV", "A_JournalEntry", "DocumentHeaderText", "AccountingDocument")
    assert spec.body == {
        "CompanyCode": "1000", "AccountingDocumentType": "KA", "DocumentDate": "/Date(1806537600000)/", "PostingDate": "/Date(1806537600000)/",
        "DocumentReferenceID": "KD/26-27/0412", "DocumentHeaderText": "SCF|AXN|1000|KD002|0412", "TransactionCurrency": "INR",
        "to_Item": {"results": [
            {"JournalEntryItem": "1", "PostingKey": "21", "Supplier": "200081", "DebitCreditCode": "S", "AmountInTransactionCurrency": "590000.00",
             "AssignmentReference": "5100004425", "DocumentItemText": "SCF KD/26-27/0412 PROGRAMME"},
            {"JournalEntryItem": "2", "PostingKey": "31", "Supplier": "9800001", "DebitCreditCode": "H", "AmountInTransactionCurrency": "590000.00",
             "DueCalculationBaseDate": "/Date(1810339200000)/", "PaymentMethod": "R", "AssignmentReference": "5100004425",
             "DocumentItemText": "SCF KD/26-27/0412 PROGRAMME"}]}}
    assert cz.check_journal(spec.body) == []
    gl = sm.scf_journal_entry(scf_payload(financier="BANKGL"), ctx, SCF_CFG, sm.scf_financier(SCF_CFG, "BANKGL")).body["to_Item"]["results"][1]
    assert gl == {"JournalEntryItem": "2", "PostingKey": "50", "GLAccount": "21600000", "DebitCreditCode": "H", "AmountInTransactionCurrency": "590000.00",
                  "AssignmentReference": "5100004425", "DocumentItemText": "SCF KD/26-27/0412 BANKGL"}
    with pytest.raises(ValueError, match="financier NOBODY has no SAP business partner"):
        sm.scf_financier(SCF_CFG, "NOBODY")


def test_scf_journal_entry_customizing_checks():
    ctx = {**CTX, "reference": "SCF|X", "currency": "INR"}
    body = sm.scf_journal_entry(scf_payload(), ctx, SCF_CFG, {"businessPartner": "9800001", "paymentMethod": "R"}).body
    items = body["to_Item"]["results"]
    assert "FI document type ZZ is not in the customizing (T003)" in cz.check_journal({**body, "AccountingDocumentType": "ZZ"})
    unbalanced = {**body, "to_Item": [items[0], {**items[1], "AmountInTransactionCurrency": "1.00"}]}
    assert any("not balanced" in p for p in cz.check_journal(unbalanced))
    assert any("is not a financier" in p for p in cz.check_journal({**body, "to_Item": [items[0], {**items[1], "Supplier": "123"}]}))
    assert any("not extended to company code 2000" in p for p in cz.check_journal({**body, "CompanyCode": "2000"}))
    assert any("payment method Q" in p for p in cz.check_journal({**body, "to_Item": [items[0], {**items[1], "PaymentMethod": "Q"}]}))
    assert cz.check_journal({**body, "to_Item": [items[0]]})[-1] == "journal entry: needs a debit and a credit line"
    assert any("needs a Supplier or a GLAccount" in p for p in cz.check_journal({**body, "to_Item": [items[0], {k: v for k, v in items[1].items() if k != "Supplier"}]}))


def test_scf_idoc_fidccp02_golden():
    ctx = {**CTX, "reference": "SCF|AXN|1000|KD002|0412"}
    xml = sm.idoc_xml("SCF_FINANCING", scf_payload(), ctx, {"cfg": SCF_CFG, "financier": {"businessPartner": "9800001", "paymentMethod": "R"}, "currency": "INR"})
    assert "<IDOCTYP>FIDCCP02</IDOCTYP><MESTYP>FIDCCH</MESTYP>" in xml
    assert ('<E1FIKPF SEGMENT="1"><BUKRS>1000</BUKRS><BLART>KA</BLART><BLDAT>20270401</BLDAT><BUDAT>20270401</BUDAT><WAERS>INR</WAERS>'
            '<XBLNR>KD/26-27/0412</XBLNR><BKTXT>SCF|AXN|1000|KD002|0412</BKTXT></E1FIKPF>') in xml
    assert ('<E1FISEG SEGMENT="1"><BUZEI>001</BUZEI><BSCHL>21</BSCHL><KOART>K</KOART><LIFNR>200081</LIFNR><WRBTR>590000.00</WRBTR>'
            '<ZUONR>5100004425</ZUONR><SGTXT>SCF KD/26-27/0412 PROGRAMME</SGTXT></E1FISEG>') in xml
    assert ('<E1FISEG SEGMENT="1"><BUZEI>002</BUZEI><BSCHL>31</BSCHL><KOART>K</KOART><LIFNR>9800001</LIFNR><WRBTR>590000.00</WRBTR>'
            '<ZFBDT>20270515</ZFBDT><ZLSCH>R</ZLSCH><ZUONR>5100004425</ZUONR><SGTXT>SCF KD/26-27/0412 PROGRAMME</SGTXT></E1FISEG>') in xml
    gl = sm.idoc_xml("SCF_FINANCING", scf_payload(), ctx, {"cfg": SCF_CFG, "financier": {"glAccount": "21600000"}})
    assert "<BSCHL>50</BSCHL><KOART>S</KOART><HKONT>21600000</HKONT>" in gl and "<WAERS>INR</WAERS>" in gl


# ================================================================ the simulator's customizing checks on outline agreements
def test_the_simulator_refuses_what_sap_would_refuse_on_an_outline_agreement():
    unknown = plan_of(contract_payload(), c=cfg(documentTypes={**sd.OUTLINE_AGREEMENT["documentTypes"], "QUANTITY_CONTRACT": "ZMK"}, contractTypes=["MK", "WK", "ZMK"]))
    assert "document type ZMK is not a purchasing document type of category K" in cz.check_outline(unknown, "QUANTITY_CONTRACT")[0]
    bare = sm.outline_agreement(contract_payload(targetValueMinor=0), {**CTX, "purch_org": None, "purch_group": None}, cfg(), "CONTRACT",
                                [{**TEXT_LINE, "priceMinor": None, "targetQty": "0"}])
    problems = cz.check_outline(bare, "VALUE_CONTRACT")
    for expected in ("header: PurchasingOrganization is missing", "header: PurchasingGroup is missing", "PurchaseContractTargetAmount is missing",
                     "item 10: ContractNetPriceAmount is missing"):
        assert any(expected in p for p in problems), expected
    no_group = plan_of(contract_payload(lines=[TEXT_LINE]), c=cfg(textItemMaterialGroup=None))
    assert any("a text item (no Material) needs a MaterialGroup" in p for p in cz.check_outline(no_group, "QUANTITY_CONTRACT"))
    odd_group = plan_of(contract_payload(lines=[TEXT_LINE]), c=cfg(textItemMaterialGroup="NOPE"))
    assert any("material group NOPE is not in the customizing" in p for p in cz.check_outline(odd_group, "QUANTITY_CONTRACT"))
    sa = plan_of(contract_payload("SCHEDULING_AGREEMENT", [{**TEXT_LINE, "plant": None}]), "SCHEDULING_AGREEMENT")
    assert any("a scheduling agreement item needs a Plant" in p for p in cz.check_outline(sa, "SCHEDULING_AGREEMENT"))
    empty = plan_of(contract_payload(lines=[]))
    assert "a MK needs at least one item" in cz.check_outline(empty, "QUANTITY_CONTRACT")
    backwards = plan_of(contract_payload(validFrom="2028-04-01"))
    assert "header: ValidityEndDate is before ValidityStartDate" in cz.check_outline(backwards, "QUANTITY_CONTRACT")
    change = plan_of(contract_payload(version=2, lines=[{**TEXT_LINE, "targetQty": None}, {**TEXT_LINE, "line": 20, "targetQty": None}]),
                     number="4600000101", existing_items={10})
    change.ops[-1].body.pop("CorrespncExternalReference")
    problems = cz.check_outline(change, "QUANTITY_CONTRACT")
    assert any("TargetQuantity is missing" in p for p in problems) and any("must PATCH the header with the new CorrespncExternalReference" in p for p in problems)
    close = plan_of(contract_payload(action="CLOSE", lines=[], validTo=None), number="4600000101")
    assert "a close needs the ValidityEndDate" in cz.check_outline(close)
    nothing = sm.OutlinePlan("CONTRACT", "CHANGE", "MK", "R", [])
    assert cz.check_outline(nothing) == ["nothing to send"]
    assert cz.odata_day("2027-04-01") == date(2027, 4, 1) and cz.odata_day("garbage") is None and cz.odata_day(None) is None


# ================================================================ sample payloads of the mock dataset (SAP_CONFIG/samples)
def samples() -> dict:
    """The sample requests and responses of backend/data/erp_mock/SAP_CONFIG/samples, built by the live mapping (regenerate with
    ``python -c "from tests.pic.test_sap_live_mapping import write_samples; write_samples()"`` from backend/ after a mapping change)."""
    out = {}
    qc = contract_payload()
    plan = plan_of(qc)
    out["OUTLINE_AGREEMENT_MK_create.request.json"] = {"message": {"type": "OUTLINE_AGREEMENT", "key": CTX["reference"], "payload": qc},
                                                       "requests": [{"method": op.method, "path": f"/sap/opu/odata/sap/{plan.service}/{op.path}", "body": op.body}
                                                                    for op in plan.ops]}
    out["OUTLINE_AGREEMENT_MK_create.response.json"] = {"status": 201, "body": {"d": {"PurchaseContract": "4600000101", "PurchaseContractType": "MK",
                                                                                      "CorrespncExternalReference": "1000|OA|QC-6"}}}
    rc = contract_payload("RATE_CARD", [TEXT_LINE], contract="RC-7101", targetValueMinor=30_000_000)
    plan = plan_of(rc)
    out["OUTLINE_AGREEMENT_WK_rate_card_create.request.json"] = {"message": {"type": "OUTLINE_AGREEMENT", "payload": rc},
                                                                 "requests": [{"method": op.method, "path": f"/sap/opu/odata/sap/{plan.service}/{op.path}",
                                                                               "body": op.body} for op in plan.ops]}
    sa = contract_payload("SCHEDULING_AGREEMENT", [{"line": 10, "material": "DC-330", "description": "Die-cast housing DC-330", "plant": "P100", "uom": "EA",
                                                    "targetQty": "24000", "priceMinor": 41800}], contract="SA-5521", targetValueMinor=0)
    plan = plan_of(sa, "SCHEDULING_AGREEMENT")
    out["OUTLINE_AGREEMENT_LP_create.request.json"] = {"message": {"type": "OUTLINE_AGREEMENT", "payload": sa},
                                                       "requests": [{"method": op.method, "path": f"/sap/opu/odata/sap/{plan.service}/{op.path}", "body": op.body}
                                                                    for op in plan.ops]}
    out["OUTLINE_AGREEMENT_LP_create.response.json"] = {"status": 201, "body": {"d": {"SchedulingAgreement": "5500000101", "PurchasingDocumentType": "LP"}}}
    changed = contract_payload(version=2, lines=[{**qc["lines"][0], "targetQty": "25000"}, {**TEXT_LINE, "line": 20}])
    plan = plan_of(changed, number="4600000101", existing_items={10})
    out["OUTLINE_AGREEMENT_MK_change.request.json"] = {"message": {"type": "OUTLINE_AGREEMENT", "payload": changed, "sapNumber": "4600000101"},
                                                       "requests": [{"method": op.method, "path": f"/sap/opu/odata/sap/{plan.service}/{op.path}", "body": op.body}
                                                                    for op in plan.ops]}
    closed = contract_payload(action="CLOSE", closeReason="TERMINATED", validTo="2027-09-30", lines=[], version=3)
    plan = plan_of(closed, number="4600000101")
    out["OUTLINE_AGREEMENT_close.request.json"] = {"message": {"type": "OUTLINE_AGREEMENT", "payload": closed, "sapNumber": "4600000101"},
                                                   "requests": [{"method": op.method, "path": f"/sap/opu/odata/sap/{plan.service}/{op.path}", "body": op.body}
                                                                for op in plan.ops]}
    rev = reversal_payload()
    spec = sm.payment_reversal(rev, {**CTX, "reference": "PAYREV|PAY-880001", "payment_service": "ZAPI_VENDOR_PAYMENT_SRV"}, sd.PAYMENT_REVERSAL,
                               {"fiscalYear": "2026", "reason": "01", "postingDate": date(2027, 1, 10)})
    out["PAYMENT_REVERSAL.request.json"] = {"message": {"type": "PAYMENT_REVERSAL", "key": "PAYREV|PAY-880001", "payload": rev},
                                            "requests": [{"method": "POST", "path": f"/sap/opu/odata/sap/{spec.service}/{spec.entity_set}", "body": spec.body}]}
    out["PAYMENT_REVERSAL.response.json"] = {"status": 201, "body": {"d": {"ReverseDocument": "1500009101", "FiscalYear": "2026",
                                                                           "AccountingDocument": "1500002210"}}}
    scf = scf_payload()
    ctx = {**CTX, "reference": "SCF|AXN|1000|KD002|0412", "currency": "INR", "journal_service": "ZAPI_JOURNAL_ENTRY_SRV"}
    spec = sm.scf_journal_entry(scf, ctx, SCF_CFG, sm.scf_financier(SCF_CFG, "PROGRAMME"))
    out["SCF_FINANCING.request.json"] = {"message": {"type": "SCF_FINANCING", "key": ctx["reference"], "payload": scf},
                                         "requests": [{"method": "POST", "path": f"/sap/opu/odata/sap/{spec.service}/{spec.entity_set}", "body": spec.body}]}
    out["SCF_FINANCING.response.json"] = {"status": 201, "body": {"d": {"AccountingDocument": "1700000101", "FiscalYear": "2027", "CompanyCode": "1000"}}}
    out["SCF_FINANCING_FIDCCP02.idoc.xml"] = sm.idoc_xml("SCF_FINANCING", scf, ctx, {"cfg": SCF_CFG, "financier": sm.scf_financier(SCF_CFG, "PROGRAMME"),
                                                                                    "currency": "INR"})
    return out


def _render(name, content) -> str:
    return content + "\n" if name.endswith(".xml") else json.dumps(content, indent=2, ensure_ascii=False) + "\n"


def write_samples() -> None:
    for name, content in samples().items():
        (cz.DIRECTORY / "samples" / name).write_text(_render(name, content), encoding="utf-8", newline="\n")


def test_the_sample_payloads_of_the_mock_dataset_are_what_the_mapping_sends():
    for name, content in samples().items():
        path = cz.DIRECTORY / "samples" / name
        assert path.exists(), f"{name} missing: run write_samples()"
        assert path.read_text(encoding="utf-8") == _render(name, content), f"{name} is stale: run write_samples()"


def test_the_mock_customizing_holds_the_document_types_reasons_and_financiers():
    c = cz.load()
    assert c.document_types["K"] == {"MK", "WK"} and c.document_types["L"] == {"LP", "LPA"} and c.document_types["F"] == {"NB", "FO", "UB"}
    assert c.document_types["B"] == {"NB"} and set(c.reversal_reasons) == {"01", "02", "03", "04", "05"}
    assert c.reversal_reasons["02"]["alternativeDate"] and not c.reversal_reasons["01"]["alternativeDate"]
    assert {"KA", "SA", "KZ"} <= c.fi_document_types and {"N", "R"} <= c.payment_methods
    assert c.financiers["9800001"] == {"1000", "1100"} and c.financiers["9800011"] == {"1000", "2000"}
    assert c.defaults["financier"]["businessPartner"] in c.financiers and c.defaults["textItemMaterialGroup"] in c.material_groups


# ================================================================ connector capabilities
def test_the_connector_maps_the_three_types_per_transport(monkeypatch):
    connector = connectors.REGISTRY["SAP_S4"]
    for key in ("URL", "IDOC_DIR", "TRANSPORT", "PAYMENT_SERVICE", "JOURNAL_SERVICE"):
        monkeypatch.delenv(f"PIC_ERP_SAP_S4_{key}", raising=False)
    assert connector.simulator and all(connectors.maps("SAP_S4", t) for t in connectors.SIMULATOR_VALIDATED)
    monkeypatch.setenv("PIC_ERP_SAP_S4_URL", "http://127.0.0.1:9")
    assert connectors.maps("SAP_S4", "OUTLINE_AGREEMENT") and connectors.maps("SAP_S4", "SCF_FINANCING") and not connectors.maps("SAP_S4", "PAYMENT_REVERSAL")
    assert connector.transport_for("SCF_FINANCING") == "idoc"
    monkeypatch.setenv("PIC_ERP_SAP_S4_PAYMENT_SERVICE", "ZAPI_VENDOR_PAYMENT_SRV")
    monkeypatch.setenv("PIC_ERP_SAP_S4_JOURNAL_SERVICE", "ZAPI_JOURNAL_ENTRY_SRV")
    assert connectors.maps("SAP_S4", "PAYMENT_REVERSAL") and connector.transport_for("SCF_FINANCING") == "odata"
    monkeypatch.setenv("PIC_ERP_SAP_S4_TRANSPORT", "idoc")
    assert connectors.maps("SAP_S4", "SCF_FINANCING") and not connectors.maps("SAP_S4", "OUTLINE_AGREEMENT") and not connectors.maps("SAP_S4", "PAYMENT_REVERSAL")
    assert sm.UNMAPPED_LIVE == () and "JOURNAL_SERVICE" in connector.SETTINGS
    assert connectors.skip_reason("NO_SUCH_ERP", None, "OUTLINE_AGREEMENT", {}) is None
    assert connectors.REGISTRY["ODOO"].skip_reason(None, "OUTLINE_AGREEMENT", {}) is None


# ================================================================ database: the simulator runs the live mapping
def axn(who="contract.manager", day=DAY):
    return ai_eval.rolled_back(ai_eval.scenario("AXN"), who, ai_eval._when(day, 10))


@pytest.fixture
def simulator(monkeypatch):
    for key in ("URL", "IDOC_DIR", "TRANSPORT", "PAYMENT_SERVICE", "JOURNAL_SERVICE", "PURCH_ORG", "PURCH_GROUP"):
        monkeypatch.delenv(f"PIC_ERP_SAP_S4_{key}", raising=False)
    yield connectors.REGISTRY["SAP_S4"]
    integration.FAULTS.update(fail=0, lose_response=0)


def rule(s, key, body, company_code=None, version=None):
    # Rows written at the same pinned business instant tie on created_at; the rules engine then picks the highest version label, so the
    # labels grow with each call (the later version of a test wins, as it would with a later creation time).
    # Effective a day after the seeded and D21 versions (2026-04-01), so a test version wins over them whatever their creation time.
    row = RuleSet(tenant_id=principal(s).tenant_id, key=key, version=version or f"T-{time.time_ns():020d}", effective_from=date(2026, 4, 2),
                  company_code=company_code, body=body, description="test")
    s.add(row)
    s.flush()
    return row


def new_contract(s, kind="QUANTITY_CONTRACT", text=False) -> Contract:
    material = s.execute(select(Material).where(Material.number == "FK-M8-50")).scalar_one()
    supplier = s.execute(select(Supplier).where(Supplier.code == "KD002")).scalar_one()
    lines = ([{"description": "Tool polishing, per hour", "plant": "P100", "uom": "H", "target_qty": "100", "unit_price_minor": 300000}] if text else
             [{"material_id": material.id, "description": "Fastener kit M8 x 50", "plant": "P100", "uom": "EA", "target_qty": "20000", "unit_price_minor": 1250}])
    contract = contract_svc.create_draft(s, type=kind, title=f"SAP mapping {kind}", supplier_id=supplier.id, company_code="1000", valid_from=date(2027, 4, 1),
                                         valid_to=date(2028, 3, 31), payment_terms="N45", incoterms="FCA Coimbatore", lines=lines,
                                         owner_id=principal(s).user_id, tolerances={})
    for pv in s.execute(select(PriceValidity).join(ContractLine, ContractLine.id == PriceValidity.contract_line_id)
                        .where(ContractLine.contract_id == contract.id)).scalars():
        pv.published = True
    contract.status = "ACTIVE"
    s.flush()
    return contract


def oa_messages(s, contract):
    return s.execute(select(IntegrationMessage).where(IntegrationMessage.message_type == "OUTLINE_AGREEMENT", IntegrationMessage.object_id == contract.id)
                     .order_by(IntegrationMessage.created_at, IntegrationMessage.id)).scalars().all()   # uuid7 ids: creation order within a pinned instant


def sap_request(s, message):
    return s.execute(select(ErpDocument).where(ErpDocument.external_ref == message.idempotency_key)).scalar_one().payload["sapRequest"]


def test_simulator_creates_changes_and_closes_an_outline_agreement_under_one_number(simulator):
    with axn() as s:
        rule(s, sd.OUTLINE_KEY, {**sd.OUTLINE_AGREEMENT, "purchasingOrg": "PO10", "purchasingGroup": "G01"}, company_code="1000")
        qc = new_contract(s)
        created = contract_svc.post_to_erp(s, qc)
        [first] = oa_messages(s, qc)
        assert created["status"] == "POSTED" and qc.erp_doc_no == created["erpDocument"] and first.erp_doc_no.startswith("46")
        request = sap_request(s, first)
        assert request["action"] == "CREATE" and request["documentType"] == "MK" and request["service"] == "API_PURCHASECONTRACT_PROCESS_SRV"
        body = request["ops"][0]["body"]
        assert (body["PurchaseContractType"], body["PurchasingOrganization"], body["PurchasingGroup"], body["CompanyCode"]) == ("MK", "PO10", "G01", "1000")
        assert body["CorrespncExternalReference"] == connectors.reference(first.idempotency_key, 12)
        # query-before-retry: the simulator finds the agreement by the message's key
        assert simulator.find(s, first).doc_no == first.erp_doc_no
        # a new version (amendment) changes the same SAP agreement: item PATCH, header PATCH with the new reference last
        line = s.execute(select(ContractLine).where(ContractLine.contract_id == qc.id)).scalar_one()
        line.target_qty = Decimal("25000")
        qc.version = 2
        changed = contract_svc.post_to_erp(s, qc)
        second = oa_messages(s, qc)[-1]
        assert changed["status"] == "POSTED" and second.erp_doc_no == first.erp_doc_no == qc.erp_doc_no
        ops = sap_request(s, second)["ops"]
        assert sap_request(s, second)["action"] == "CHANGE" and [o["method"] for o in ops] == ["PATCH", "PATCH"]
        assert ops[0]["body"]["TargetQuantity"] == "25000.000" and ops[-1]["path"] == f"A_PurchaseContract('{first.erp_doc_no}')"
        # termination: the CLOSE message ends the agreement on the last day in force, exactly once per version
        qc.version, qc.status = 3, "TERMINATED"
        closed = contract_svc._close_contract(s, SimpleNamespace(object_id=qc.id, topic="contract.terminated", payload={"effectiveFrom": "2027-10-01"}))
        third = oa_messages(s, qc)[-1]
        assert closed["status"] == "POSTED" and third.idempotency_key.endswith("|v3|CLOSE") and third.erp_doc_no == first.erp_doc_no
        assert sap_request(s, third)["ops"] == [{"method": "PATCH", "path": f"A_PurchaseContract('{first.erp_doc_no}')",
                                                 "body": {"ValidityEndDate": "/Date(1822262400000)/", "CorrespncExternalReference": connectors.reference(third.idempotency_key, 12)}}]
        assert contract_svc.close_in_erp(s, qc, date(2027, 9, 30), "TERMINATED")["erpDocument"] == first.erp_doc_no
        assert len(oa_messages(s, qc)) == 3
        # nothing to close when the agreement ends anyway, or when the contract never reached the ERP
        assert contract_svc.close_in_erp(s, qc, date(2028, 3, 31), "RENEWED") is None
        assert contract_svc._close_contract(s, SimpleNamespace(object_id=uuid.uuid4(), topic="contract.terminated", payload={})) is None


def test_renewal_closes_the_predecessor_the_day_before_its_successor_starts(simulator):
    with axn() as s:
        qc = new_contract(s)
        contract_svc.post_to_erp(s, qc)
        result = contract_svc._close_contract(s, SimpleNamespace(object_id=qc.id, topic="contract.renewed", payload={"validFrom": "2028-01-01"}))
        message = oa_messages(s, qc)[-1]
        assert result["status"] == "POSTED" and message.payload["closeReason"] == "RENEWED" and message.payload["validTo"] == "2027-12-31"
        # a never-sent contract (no message, no ERP number) is not closed
        fresh = new_contract(s)
        assert contract_svc.close_in_erp(s, fresh, date(2027, 12, 31), "RENEWED") is None


def test_value_contract_text_lines_take_the_simulator_material_group_and_rate_cards_are_wk(simulator):
    with axn() as s:
        rc = new_contract(s, "RATE_CARD", text=True)
        assert contract_svc.post_to_erp(s, rc)["status"] == "POSTED"
        body = sap_request(s, oa_messages(s, rc)[0])["ops"][0]["body"]
        [item] = body["to_PurchaseContractItem"]["results"]
        assert body["PurchaseContractType"] == "WK" and body["PurchaseContractTargetAmount"] == "300000.00"
        assert item["MaterialGroup"] == cz.load().defaults["textItemMaterialGroup"] and item["AccountAssignmentCategory"] == "U" and "Material" not in item
        assert body["PurchasingGroup"]      # rule empty: master / mock customizing fallbacks of the simulator


def test_legal_documents_and_switched_off_types_are_not_sent_and_say_so(simulator):
    with axn() as s:
        nda = new_contract(s)
        nda.type = "NDA"
        assert contract_svc.post_to_erp(s, nda) is None and oa_messages(s, nda) == []          # never a message for a legal document
        sow = new_contract(s, "SOW", text=True)
        rule(s, sd.OUTLINE_KEY, {**sd.OUTLINE_AGREEMENT, "notSent": ["MASTER_AGREEMENT", "NDA", "SOW"],
                                 "documentTypes": {k: v for k, v in sd.OUTLINE_AGREEMENT["documentTypes"].items() if k != "SOW"}}, company_code="1000")
        result = contract_svc.post_to_erp(s, sow)
        assert result["status"] == "NOT_SENT" and "SOW is a legal document that is not sent" in result["reason"] and oa_messages(s, sow) == []
        audit = s.execute(select(AuditEvent).where(AuditEvent.object_id == sow.id, AuditEvent.action == "ERP_NOT_SENT")).scalar_one()
        assert audit.after["messageType"] == "OUTLINE_AGREEMENT"
        # a close the rule switches off
        qc = new_contract(s)
        contract_svc.post_to_erp(s, qc)
        rule(s, sd.OUTLINE_KEY, {**sd.OUTLINE_AGREEMENT, "closeOnTermination": False}, company_code="1000")
        off = contract_svc.close_in_erp(s, qc, date(2027, 9, 30), "TERMINATED")
        assert off["status"] == "NOT_SENT" and "closeOnTermination is off" in off["reason"]
        # a document type in neither list is not sent either (and the connector refuses such a message if one is queued anyway)
        rule(s, sd.OUTLINE_KEY, {**sd.OUTLINE_AGREEMENT, "documentTypes": {**sd.OUTLINE_AGREEMENT["documentTypes"], "QUANTITY_CONTRACT": "ZMK"}},
             company_code="1000")
        assert "is in neither contractTypes nor schedulingAgreementTypes" in simulator.skip_reason(s, "OUTLINE_AGREEMENT", {"type": "QUANTITY_CONTRACT", "companyCode": "1000"})
        stray = IntegrationMessage(tenant_id=qc.tenant_id, target_system="SAP_S4", message_type="OUTLINE_AGREEMENT", idempotency_key="T|OA|stray",
                                   object_type="CONTRACT", object_id=qc.id, object_ref=qc.number, payload={**contract_payload(), "companyCode": "1000"},
                                   payload_hash="x", status="PENDING", attempts=0)
        with pytest.raises(connectors.ConnectorRejected, match="is not sent to SAP"):
            simulator.post(s, stray)


def test_the_simulator_refuses_a_document_type_the_mock_customizing_does_not_have(simulator):
    with axn() as s:
        rule(s, sd.OUTLINE_KEY, {**sd.OUTLINE_AGREEMENT, "contractTypes": ["MK", "WK", "ZWK"],
                                 "documentTypes": {**sd.OUTLINE_AGREEMENT["documentTypes"], "VALUE_CONTRACT": "ZWK"}}, company_code="1000")
        vc = new_contract(s, "VALUE_CONTRACT", text=True)
        result = contract_svc.post_to_erp(s, vc)
        [message] = oa_messages(s, vc)
        assert result["status"] == "RETRY" and "SAP sandbox simulator refused the OUTLINE_AGREEMENT" in message.last_error
        assert "document type ZWK is not a purchasing document type of category K" in message.last_error and vc.erp_doc_no is None


def test_a_later_version_waits_for_an_earlier_one_still_retrying(simulator):
    with axn() as s:
        qc = new_contract(s)
        integration.FAULTS["fail"] = 1
        assert contract_svc.post_to_erp(s, qc)["status"] == "RETRY"
        qc.version = 2
        qc.valid_to = date(2028, 6, 30)
        waiting = contract_svc.post_to_erp(s, qc)
        second = oa_messages(s, qc)[-1]
        assert waiting["status"] == "RETRY" and "has to reach SAP first" in second.last_error
        integration.process(s, oa_messages(s, qc)[0])
        integration.process(s, second)
        assert second.status == "POSTED" and second.erp_doc_no == oa_messages(s, qc)[0].erp_doc_no
        assert sap_request(s, second)["action"] == "CHANGE"


def test_a_migrated_contract_with_an_sap_number_is_changed_not_created(simulator):
    with axn() as s:
        qc = new_contract(s)
        qc.erp_doc_no = "4600099999"
        contract_svc.post_to_erp(s, qc)
        [message] = oa_messages(s, qc)
        assert message.erp_doc_no == "4600099999" and sap_request(s, message)["action"] == "CHANGE"
        assert [o["method"] for o in sap_request(s, message)["ops"]] == ["POST", "PATCH"]    # SAP has no item yet as far as PIC knows


def payment_and_invoice(s):
    payment = s.execute(select(Payment).order_by(Payment.value_date, Payment.number).limit(1)).scalar_one()
    return payment, s.get(Invoice, payment.invoice_id)


def message(s, kind, key, payload, object_id, object_type="INVOICE"):
    row = integration.enqueue(s, target_system="SAP_S4", message_type=kind, idempotency_key=key, object_type=object_type, object_id=object_id,
                              object_ref="T", payload=payload)
    return row


def test_simulator_reverses_a_payment_with_reason_and_posting_date_and_finds_it_again(simulator):
    with axn("finance.controller") as s:
        payment, invoice = payment_and_invoice(s)
        for period in s.execute(select(PostingPeriod).where(PostingPeriod.company_code == invoice.company_code,
                                                            PostingPeriod.period == payment.value_date.strftime("%Y-%m"))).scalars():
            s.delete(period)                                           # open period first (a database with the finance pack D15 closed some)
        rule(s, sd.REVERSAL_KEY, dict(sd.PAYMENT_REVERSAL), company_code=invoice.company_code)
        s.flush()
        msg = message(s, "PAYMENT_REVERSAL", f"PAYREV|T|{payment.number}", reversal_payload(payment=payment.number, companyCode=invoice.company_code), invoice.id)
        integration.FAULTS["lose_response"] = 1                        # SAP posts, the answer is lost: query-before-retry finds it
        integration.process(s, msg)
        assert msg.status == "POSTED" and msg.erp_doc_no.startswith("15000")
        body = sap_request(s, msg)["body"]
        assert body["ReversalReason"] == "01" and cz.odata_day(body["PostingDate"]) == payment.value_date and body["ResetClearing"] is True
        start = payment.value_date.year if payment.value_date.month >= 4 else payment.value_date.year - 1
        assert body["FiscalYear"] == str(start) and simulator.find(s, msg).doc_no == msg.erp_doc_no
        # the payment's period closed in PIC: reason 02 with the return date
        s.add(PostingPeriod(tenant_id=invoice.tenant_id, company_code=invoice.company_code, period=payment.value_date.strftime("%Y-%m"), status="CLOSED"))
        s.flush()
        closed = message(s, "PAYMENT_REVERSAL", f"PAYREV|T2|{payment.number}", reversal_payload(payment=payment.number, companyCode=invoice.company_code), invoice.id)
        integration.process(s, closed)
        assert closed.status == "POSTED" and sap_request(s, closed)["body"]["ReversalReason"] == "02"
        # a rule the mock customizing does not allow: reason 01 with the return date
        rule(s, sd.REVERSAL_KEY, {"reversalReason": "01", "postingDate": "RETURN_DATE", "closedPeriodReason": None}, company_code=invoice.company_code)
        refused = message(s, "PAYMENT_REVERSAL", f"PAYREV|T3|{payment.number}", reversal_payload(payment=payment.number, companyCode=invoice.company_code), invoice.id)
        integration.process(s, refused)
        assert refused.status == "RETRY" and "does not allow an alternative posting date" in refused.last_error
        unknown = message(s, "PAYMENT_REVERSAL", "PAYREV|T4|NO-SUCH", reversal_payload(payment="NO-SUCH", clearingDocument=None), invoice.id)
        integration.process(s, unknown)
        assert unknown.status == "RETRY" and "has no clearing document" in unknown.last_error


def test_simulator_posts_the_scf_journal_entry_with_the_configured_or_the_mock_financier(simulator):
    with axn("ap.clerk") as s:
        _, invoice = payment_and_invoice(s)
        default = message(s, "SCF_FINANCING", "SCF|T|1", scf_payload(companyCode=invoice.company_code), invoice.id)
        integration.process(s, default)
        body = sap_request(s, default)["body"]
        assert default.status == "POSTED" and body["to_Item"]["results"][1]["Supplier"] == cz.load().defaults["financier"]["businessPartner"]
        assert simulator.find(s, default).doc_no == default.erp_doc_no
        rule(s, sd.SCF_KEY, {"financiers": {"PROGRAMME": {"glAccount": "21600000"}}}, company_code=invoice.company_code)
        gl = message(s, "SCF_FINANCING", "SCF|T|2", scf_payload(companyCode=invoice.company_code), invoice.id)
        integration.process(s, gl)
        assert gl.status == "POSTED" and sap_request(s, gl)["body"]["to_Item"]["results"][1]["GLAccount"] == "21600000"
        rule(s, sd.SCF_KEY, {"financiers": {"PROGRAMME": {"businessPartner": "7777777"}}}, company_code=invoice.company_code)
        bad = message(s, "SCF_FINANCING", "SCF|T|3", scf_payload(companyCode=invoice.company_code), invoice.id)
        integration.process(s, bad)
        assert bad.status == "RETRY" and "business partner 7777777 is not a financier" in bad.last_error


# ================================================================ database: the live connector against the loopback SAP mock
@pytest.fixture
def sap(monkeypatch):
    mock = SapMock()
    url = mock.start()
    for key in ("IDOC_DIR", "TRANSPORT", "PAYMENT_SERVICE", "JOURNAL_SERVICE", "PURCH_ORG", "PURCH_GROUP", "TERMS_MAP"):
        monkeypatch.delenv(f"PIC_ERP_SAP_S4_{key}", raising=False)
    monkeypatch.setenv("PIC_ERP_SAP_S4_URL", url)
    monkeypatch.setenv("PIC_ERP_SAP_S4_USER", "PIC_TECH")
    monkeypatch.setenv("PIC_ERP_SAP_S4_PASSWORD", "not-a-real-secret")
    monkeypatch.setenv("PIC_ERP_SAP_S4_SAP_CLIENT", "100")
    monkeypatch.setenv("PIC_ERP_SAP_S4_RETRIES", "1")
    monkeypatch.setattr("time.sleep", lambda s: None)
    yield mock
    mock.stop()


def live_rule(s):
    rule(s, sd.OUTLINE_KEY, {**sd.OUTLINE_AGREEMENT, "purchasingOrg": "PO10", "purchasingGroup": "G01", "textItemMaterialGroup": "SERVICES"}, company_code="1000")


def test_live_contract_create_change_close_against_the_sap_mock(sap, monkeypatch):
    monkeypatch.setenv("PIC_ERP_SAP_S4_TERMS_MAP", "N45=Z045")
    connector = connectors.REGISTRY["SAP_S4"]
    with axn() as s:
        live_rule(s)
        qc = new_contract(s)
        created = contract_svc.post_to_erp(s, qc)
        entity, body = [(e, b) for e, b in sap.created if e == "A_PurchaseContract"][-1]
        assert created["status"] == "POSTED" and created["erpDocument"] == body["_number"] and qc.erp_doc_no == body["_number"]
        assert body["PurchaseContractType"] == "MK" and body["PaymentTerms"] == "Z045" and body["Supplier"] == connector._vendor_number(s, "KD002")
        first = oa_messages(s, qc)[0]
        assert connector.find(s, first).doc_no == qc.erp_doc_no
        # change: the item SAP has is PATCHed, the new one POSTed, the header PATCH carries the new reference
        line = s.execute(select(ContractLine).where(ContractLine.contract_id == qc.id)).scalar_one()
        line.target_qty = Decimal("30000")
        s.add(ContractLine(tenant_id=qc.tenant_id, contract_id=qc.id, line_no=20, description="Packing service", plant="P100", uom="EA", target_qty=Decimal("10")))
        qc.version = 2
        s.flush()
        update, failures = sap_odata.ODataClient.update, []

        def header_locked_once(self, service, path, body):          # the items went through, the header PATCH fails once
            if path.startswith("A_PurchaseContract(") and "CorrespncExternalReference" in body and not failures:
                failures.append(path)
                raise connectors.ConnectorRejected("HTTP 423 from SAP: purchase contract is locked by user BUYER01")
            return update(self, service, path, body)
        monkeypatch.setattr(sap_odata.ODataClient, "update", header_locked_once)
        failed = contract_svc.post_to_erp(s, qc)
        second = oa_messages(s, qc)[-1]
        assert failed["status"] == "RETRY" and failures and connector.find(s, second) is None   # not found until every write went through
        integration.process(s, second)
        assert second.status == "POSTED" and second.erp_doc_no == qc.erp_doc_no
        assert connector.find(s, second).doc_no == qc.erp_doc_no
        new_items = [b for e, b in sap.created if e == "A_PurchaseContractItem" and b.get("PurchaseContractItem") == "20"]
        assert len(new_items) == 1 and new_items[0]["MaterialGroup"] == "SERVICES" and "ContractNetPriceAmount" not in new_items[0]   # posted once; no price yet
        patched_item = [b for e, b in sap.created if e == "A_PurchaseContractItem" and b.get("PurchaseContractItem") == "10"][0]
        assert patched_item["TargetQuantity"] == "30000.000"
        # close
        qc.version = 3
        result = contract_svc.close_in_erp(s, qc, date(2027, 9, 30), "TERMINATED")
        assert result["status"] == "POSTED" and sap.patched[-1][2]["ValidityEndDate"] == "/Date(1822262400000)/"


def test_live_scheduling_agreement_goes_to_the_scheduling_agreement_api(sap):
    with axn() as s:
        live_rule(s)
        sa = new_contract(s, "SCHEDULING_AGREEMENT")
        assert contract_svc.post_to_erp(s, sa)["status"] == "POSTED"
        entity, body = sap.created[-1]
        assert entity == "A_SchAgrmtHeader" and body["PurchasingDocumentType"] == "LP" and sa.erp_doc_no.startswith("55000")
        assert sap.requests[-1]["path"].endswith("/API_SCHED_AGRMT_PROCESS_SRV/A_SchAgrmtHeader")


def test_live_mode_rejects_missing_configuration_instead_of_guessing(sap):
    connector = connectors.REGISTRY["SAP_S4"]
    with axn() as s:
        rule(s, sd.OUTLINE_KEY, dict(sd.OUTLINE_AGREEMENT), company_code="1000")     # the defaults (no org, group, material group), also after D21
        for org in s.execute(select(PurchasingOrg).where(PurchasingOrg.company_code == "1000")).scalars():
            s.delete(org)
        s.flush()
        qc = new_contract(s)
        contract_svc.post_to_erp(s, qc)
        [msg] = oa_messages(s, qc)
        assert msg.status == "RETRY" and "no SAP purchasingOrg for outline agreements" in msg.last_error
        s.add(PurchasingOrg(tenant_id=qc.tenant_id, code="PO10", name="Central", company_code="1000", active=True))
        s.flush()
        integration.process(s, msg)
        assert msg.status == "RETRY" and "no SAP purchasingGroup" in msg.last_error              # one org found, no group master for it
        rule(s, sd.OUTLINE_KEY, {**sd.OUTLINE_AGREEMENT, "purchasingGroup": "G01"}, company_code="1000")
        rc = new_contract(s, "RATE_CARD", text=True)
        contract_svc.post_to_erp(s, rc)
        [text_msg] = oa_messages(s, rc)
        assert text_msg.status == "RETRY" and "set textItemMaterialGroup" in text_msg.last_error
        integration.process(s, msg)
        assert msg.status == "POSTED" and connector.find(s, msg).doc_no == msg.erp_doc_no
        # SCF without a configured financier is refused in live mode (the simulator would use its mock financier)
        _, invoice = payment_and_invoice(s)
        scf = message(s, "SCF_FINANCING", "SCF|LIVE|0", scf_payload(companyCode=invoice.company_code, financier="NOBODY"), invoice.id)
        integration.process(s, scf)
        assert scf.status == "RETRY" and "the SCF posting needs the client's design" in scf.last_error


def test_live_payment_reversal_and_scf_on_the_customer_services(sap, monkeypatch):
    monkeypatch.setenv("PIC_ERP_SAP_S4_PAYMENT_SERVICE", "ZAPI_VENDOR_PAYMENT_SRV")
    monkeypatch.setenv("PIC_ERP_SAP_S4_JOURNAL_SERVICE", "ZAPI_JOURNAL_ENTRY_SRV")
    connector = connectors.REGISTRY["SAP_S4"]
    with axn("finance.controller") as s:
        payment, invoice = payment_and_invoice(s)
        rev = message(s, "PAYMENT_REVERSAL", f"PAYREV|LIVE|{payment.number}", reversal_payload(payment=payment.number, companyCode=invoice.company_code), invoice.id)
        integration.process(s, rev)
        entity, body = sap.created[-1]
        assert rev.status == "POSTED" and entity == "A_VendorPaymentReversal" and rev.erp_doc_no == body["_number"]
        assert body["ReversalReason"] == "01" and sap.requests[-1]["path"].endswith("/ZAPI_VENDOR_PAYMENT_SRV/A_VendorPaymentReversal")
        assert connector.find(s, rev).doc_no == rev.erp_doc_no
        rule(s, sd.SCF_KEY, {"financiers": {"PROGRAMME": {"businessPartner": "9800001", "paymentMethod": "R"}}}, company_code=invoice.company_code)
        scf = message(s, "SCF_FINANCING", "SCF|LIVE|1", scf_payload(companyCode=invoice.company_code), invoice.id)
        integration.process(s, scf)
        entity, body = sap.created[-1]
        assert scf.status == "POSTED" and entity == "A_JournalEntry" and body["to_Item"]["results"][1]["Supplier"] == "9800001"
        assert connector.find(s, scf).doc_no == scf.erp_doc_no


def test_live_scf_without_a_journal_service_is_an_fidccp02_idoc_and_reversal_is_not_mapped(sap, monkeypatch, tmp_path):
    connector = connectors.REGISTRY["SAP_S4"]
    with axn("ap.clerk") as s:
        _, invoice = payment_and_invoice(s)
        rule(s, sd.SCF_KEY, {"financiers": {"PROGRAMME": {"businessPartner": "9800001"}}}, company_code=invoice.company_code)
        scf = message(s, "SCF_FINANCING", "SCF|IDOC|1", scf_payload(companyCode=invoice.company_code), invoice.id)
        integration.process(s, scf)
        assert scf.status == "POSTED" and "<IDOCTYP>FIDCCP02</IDOCTYP>" in sap.idocs[-1] and "<LIFNR>9800001</LIFNR>" in sap.idocs[-1]
        assert connector.find(s, scf) is None                       # the ICF IDoc port has no query by reference
        assert not connectors.maps("SAP_S4", "PAYMENT_REVERSAL")
        monkeypatch.setenv("PIC_ERP_SAP_S4_TRANSPORT", "idoc-file")
        monkeypatch.setenv("PIC_ERP_SAP_S4_IDOC_DIR", str(tmp_path))
        filed = message(s, "SCF_FINANCING", "SCF|IDOC|2", scf_payload(companyCode=invoice.company_code), invoice.id)
        integration.process(s, filed)
        assert filed.status == "POSTED" and connector.find(s, filed).doc_no == connectors.reference("SCF|IDOC|2", 25)


def test_live_find_for_an_outline_type_that_is_not_sent_is_none(sap):
    connector = connectors.REGISTRY["SAP_S4"]
    with axn() as s:
        qc = new_contract(s)
        msg = IntegrationMessage(tenant_id=qc.tenant_id, target_system="SAP_S4", message_type="OUTLINE_AGREEMENT", idempotency_key="T|OA|NDA",
                                 object_type="CONTRACT", object_id=qc.id, object_ref=qc.number, payload={**contract_payload("NDA", [])},
                                 payload_hash="x", status="PENDING", attempts=0, created_at=datetime.now().astimezone())
        assert connector.find(s, msg) is None
