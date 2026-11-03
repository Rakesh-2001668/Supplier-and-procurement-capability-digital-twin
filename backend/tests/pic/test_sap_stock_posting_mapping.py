"""STOCK_POSTING in the SAP S/4HANA connector: golden OData and IDoc payloads for every movement type PIC posts, the validations, and a round trip
against the loopback SAP mock (tests/pic/sap_mock.py: a local HTTP server, no network, no secrets) that returns a material document number which PIC
stores as ``erpDocument``.

VALIDATED AGAINST THE MOCK ONLY: the field names are those of API_MATERIAL_DOCUMENT_SRV / BAPI_GOODSMVT_CREATE (MBGMCR03) as documented by SAP, the
assumptions are listed in platform/sap_mapping.py. A real SAP sandbox must confirm them before go-live.
"""
import json
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.pic.models import AuditEvent, IntegrationMessage, Material, StorageLocation
from app.pic.platform import connectors, integration, sap_mapping as sm, sap_odata
from app.pic.services import inventory
from app.pic.tools import ai_eval

from .sap_mock import SapMock

CTX = {"version": 2, "today": date(2026, 11, 9), "reference": "STP|STP-1001", "stock_cost_center": None, "reason_map": {"DAMAGED": "0001"}}
UOMS = {"11000002": "KG", "11000003": "EA"}


def line(material, qty, movement, **kw):
    return {"material": material, "batch": kw.get("batch", ""), "qty": qty, "movement": movement, "fromPlant": kw.get("fp", "1100"),
            "fromStorageLocation": kw.get("fs", "0001"), "fromStockType": kw.get("ft", "UNRESTRICTED"), "toPlant": kw.get("tp"),
            "toStorageLocation": kw.get("ts"), "toStockType": kw.get("tt"), "valueMinor": 100}


def posting(kind, lines, **kw):
    return {"posting": kw.pop("number", "STP-1001"), "type": kind, "plant": "1100", "postingDate": "2026-11-09", "grossMinor": 100,
            "reasonCode": kw.pop("reason_code", None), "reason": kw.pop("reason", None), "companyCode": "1000", "lines": lines, **kw}


def items(payload, object_type="STOCK_POSTING", ctx=CTX):
    return sm.stock_items(object_type, payload, UOMS, ctx)


def bodies(payload, object_type="STOCK_POSTING", ctx=CTX):
    return [(spec.code, spec.body) for spec in sm.stock_posting(object_type, payload, ctx, items(payload, object_type, ctx))]


def rows(body):
    r = body["to_MaterialDocumentItem"]
    return r["results"] if isinstance(r, dict) else r


DATE_MS = "/Date(1794182400000)/"      # 2026-11-09 00:00 UTC, the OData v2 JSON form of the posting date (same as the goods receipt)


# ================================================================ golden payloads, OData
def test_transfer_within_a_plant_311_golden():
    [(code, body)] = bodies(posting("TRANSFER", [line("11000002", "60.000", "311", tp="1100", ts="0002", tt="UNRESTRICTED")]))
    assert code == "04" and body == {
        "PostingDate": DATE_MS, "DocumentDate": DATE_MS, "GoodsMovementCode": "04", "MaterialDocumentHeaderText": "STP|STP-1001", "ReferenceDocument": "STP-1001",
        "to_MaterialDocumentItem": {"results": [{"Material": "11000002", "Plant": "1100", "StorageLocation": "0001", "GoodsMovementType": "311",
                                                 "QuantityInEntryUnit": "60.000", "EntryUnit": "KG", "IssuingOrReceivingStorageLoc": "0002",
                                                 "MaterialDocumentItemText": "STP-1001"}]}}


def test_transfer_between_plants_301_with_batch_and_blocked_stock_golden():
    [(code, body)] = bodies(posting("TRANSFER", [line("11000003", "5", "301", batch="L2609A", ft="BLOCKED", tp="1200", ts="0001", tt="BLOCKED")]))
    assert code == "04" and rows(body) == [{
        "Material": "11000003", "Plant": "1100", "StorageLocation": "0001", "Batch": "L2609A", "GoodsMovementType": "301", "InventoryStockType": "03",
        "QuantityInEntryUnit": "5.000", "EntryUnit": "EA", "IssuingOrReceivingPlant": "1200", "IssuingOrReceivingStorageLoc": "0001", "IssgOrRcvgBatch": "L2609A",
        "MaterialDocumentItemText": "STP-1001"}]


@pytest.mark.parametrize("movement,kind,stock_type", [("344", "BLOCK", "UNRESTRICTED"), ("343", "UNBLOCK", "BLOCKED")])
def test_block_344_and_unblock_343_golden(movement, kind, stock_type):
    [(code, body)] = bodies(posting(kind, [line("11000003", "2.500", movement, ft=stock_type, tp="1100", ts="0001", tt="BLOCKED" if movement == "344" else "UNRESTRICTED")],
                                    reason_code="QUALITY_DOUBT" if movement == "344" else None))
    assert code == "04"
    assert rows(body) == [{"Material": "11000003", "Plant": "1100", "StorageLocation": "0001", "GoodsMovementType": movement, "QuantityInEntryUnit": "2.500",
                           "EntryUnit": "EA", "MaterialDocumentItemText": "STP-1001"}]        # no stock type, no receiving fields: the movement type says it all


def test_scrap_551_golden_with_cost_centre_reason_mapping_and_blocked_stock():
    p = posting("SCRAP", [line("11000002", "4.000", "551", ft="BLOCKED")], number="STP-1002", reason_code="DAMAGED", reason="Crushed cartons", costObject="COST_CENTER:1120")
    [(code, body)] = bodies(p)
    assert code == "03" and body["ReferenceDocument"] == "STP-1002"
    assert rows(body) == [{"Material": "11000002", "Plant": "1100", "StorageLocation": "0001", "GoodsMovementType": "551", "InventoryStockType": "03",
                           "QuantityInEntryUnit": "4.000", "EntryUnit": "KG", "CostCenter": "1120", "GoodsMovementReasonCode": "0001",
                           "MaterialDocumentItemText": "STP-1002 DAMAGED"}]


def test_scrap_uses_the_configured_default_cost_centre_and_a_wbs_element_when_the_document_names_one():
    p = posting("SCRAP", [line("11000002", "1", "551")], reason_code="OTHER")
    [(_, body)] = bodies(p, ctx={**CTX, "stock_cost_center": "9900"})
    assert rows(body)[0]["CostCenter"] == "9900" and "GoodsMovementReasonCode" not in rows(body)[0]       # an unmapped reason travels in the item text only
    [(_, body)] = bodies({**p, "costObject": "WBS:C-2207"})
    assert rows(body)[0]["WBSElement"] == "C-2207" and "CostCenter" not in rows(body)[0]


def test_count_differences_701_702_are_two_material_documents_one_per_goods_movement_code():
    count = {"inventory": "PHI-1001", "plant": "1100", "storageLocation": "0001", "grossMinor": 5, "companyCode": "1000",
             "lines": [{"material": "11000002", "batch": "", "qty": "3.000", "movement": "701", "valueMinor": 3},
                       {"material": "11000003", "batch": "", "qty": "-2.000", "movement": "702", "valueMinor": 2}]}
    ctx = {**CTX, "reference": "PHI|PHI-1001"}
    docs = bodies(count, "PHYSICAL_INVENTORY", ctx)
    assert [c for c, _ in docs] == ["03", "05"]                                            # loss (issue) first, gain (other receipt) second: code order
    loss, gain = docs[0][1], docs[1][1]
    assert loss["MaterialDocumentHeaderText"] == "PHI|PHI-1001-03" and gain["MaterialDocumentHeaderText"] == "PHI|PHI-1001-05"
    assert loss["ReferenceDocument"] == gain["ReferenceDocument"] == "PHI-1001"
    assert rows(loss) == [{"Material": "11000003", "Plant": "1100", "StorageLocation": "0001", "GoodsMovementType": "702", "QuantityInEntryUnit": "2.000", "EntryUnit": "EA",
                           "MaterialDocumentItemText": "PHI-1001"}]
    assert rows(gain)[0]["GoodsMovementType"] == "701" and rows(gain)[0]["QuantityInEntryUnit"] == "3.000" and rows(gain)[0]["EntryUnit"] == "KG"
    assert sm.stock_codes(count) == ["03", "05"] and sm.stock_codes({"lines": [count["lines"][0]]}) == ["05"]


def test_reservation_issue_201_golden_and_fefo_batches_are_separate_items():
    issue = {"reservation": "RSV-1001", "plant": "1100", "storageLocation": "0001", "costObject": "COST_CENTER:1120", "grossMinor": 9, "companyCode": "1000",
             "lines": [{"material": "11000002", "batch": "L2609A", "qty": "10.000", "movement": "201"}, {"material": "11000002", "batch": "L2610B", "qty": "5.000", "movement": "201"}]}
    [(code, body)] = bodies(issue, "STOCK_RESERVATION", {**CTX, "reference": "RSV|RSV-1001|15.000"})
    assert code == "03" and body["ReferenceDocument"] == "RSV-1001" and body["MaterialDocumentHeaderText"] == "RSV|RSV-1001|15.000"
    assert rows(body) == [
        {"Material": "11000002", "Plant": "1100", "StorageLocation": "0001", "Batch": "L2609A", "GoodsMovementType": "201", "QuantityInEntryUnit": "10.000", "EntryUnit": "KG",
         "CostCenter": "1120", "MaterialDocumentItemText": "RSV-1001"},
        {"Material": "11000002", "Plant": "1100", "StorageLocation": "0001", "Batch": "L2610B", "GoodsMovementType": "201", "QuantityInEntryUnit": "5.000", "EntryUnit": "KG",
         "CostCenter": "1120", "MaterialDocumentItemText": "RSV-1001"}]


def test_odata_v4_sends_the_items_as_a_plain_list_and_the_stock_type_map_can_be_overridden():
    p = posting("TRANSFER", [line("11000002", "1", "311", ft="BLOCKED", tp="1100", ts="0002")])
    [(_, body)] = bodies(p, ctx={**CTX, "version": 4, "stock_type_codes": {"BLOCKED": "07"}})
    assert body["PostingDate"] == "2026-11-09" and isinstance(body["to_MaterialDocumentItem"], list) and body["to_MaterialDocumentItem"][0]["InventoryStockType"] == "07"


# ================================================================ golden payloads, IDoc
def test_idoc_mbgmcr03_golden_for_a_transfer_and_a_scrap():
    p = posting("TRANSFER", [line("11000002", "60.000", "311", tp="1100", ts="0002")])
    xml = sm.idoc_xml("STOCK_POSTING", p, CTX, {"code": "04", "items": items(p), "objectType": "STOCK_POSTING"})
    assert xml == (
        '<?xml version="1.0" encoding="UTF-8"?><MBGMCR03><IDOC BEGIN="1"><EDI_DC40 SEGMENT="1"><TABNAM>EDI_DC40</TABNAM><DIRECT>2</DIRECT><IDOCTYP>MBGMCR03</IDOCTYP>'
        '<MESTYP>MBGMCR</MESTYP><SNDPOR>PIC</SNDPOR><SNDPRT>LS</SNDPRT><SNDPRN>PICCLOUD</SNDPRN><RCVPOR>SAPS4</RCVPOR><RCVPRT>LS</RCVPRT><RCVPRN>S4HCLNT</RCVPRN>'
        '<ARCKEY>STP|STP-1001</ARCKEY></EDI_DC40><E1BP2017_GM_HEAD_01 SEGMENT="1"><PSTNG_DATE>20261109</PSTNG_DATE><DOC_DATE>20261109</DOC_DATE><REF_DOC_NO>STP-1001</REF_DOC_NO>'
        '<HEADER_TXT>STP|STP-1001</HEADER_TXT></E1BP2017_GM_HEAD_01><E1BP2017_GM_CODE SEGMENT="1"><GM_CODE>04</GM_CODE></E1BP2017_GM_CODE><E1BP2017_GM_ITEM_CREATE SEGMENT="1">'
        '<MATERIAL>11000002</MATERIAL><PLANT>1100</PLANT><STGE_LOC>0001</STGE_LOC><MOVE_TYPE>311</MOVE_TYPE><ENTRY_QNT>60.000</ENTRY_QNT><ENTRY_UOM>KG</ENTRY_UOM>'
        '<MOVE_STLOC>0002</MOVE_STLOC><ITEM_TEXT>STP-1001</ITEM_TEXT></E1BP2017_GM_ITEM_CREATE></IDOC></MBGMCR03>')
    s = posting("SCRAP", [line("11000003", "2", "551", ft="BLOCKED", batch="L2610A")], number="STP-1002", reason_code="DAMAGED", costObject="COST_CENTER:1120")
    xml = sm.idoc_xml("STOCK_POSTING", s, {**CTX, "reference": "STP|STP-1002"}, {"code": "03", "items": items(s), "objectType": "STOCK_POSTING"})
    assert ("<E1BP2017_GM_CODE SEGMENT=\"1\"><GM_CODE>03</GM_CODE></E1BP2017_GM_CODE><E1BP2017_GM_ITEM_CREATE SEGMENT=\"1\"><MATERIAL>11000003</MATERIAL><PLANT>1100</PLANT>"
            "<STGE_LOC>0001</STGE_LOC><BATCH>L2610A</BATCH><MOVE_TYPE>551</MOVE_TYPE><STCK_TYPE>S</STCK_TYPE><ENTRY_QNT>2.000</ENTRY_QNT><ENTRY_UOM>EA</ENTRY_UOM>"
            "<COSTCENTER>1120</COSTCENTER><MOVE_REAS>0001</MOVE_REAS><ITEM_TEXT>STP-1002 DAMAGED</ITEM_TEXT></E1BP2017_GM_ITEM_CREATE>") in xml
    assert "<REF_DOC_NO>STP-1002</REF_DOC_NO>" in xml and "<HEADER_TXT>STP|STP-1002</HEADER_TXT>" in xml


def test_no_secret_or_credential_is_part_of_any_payload():
    p = posting("SCRAP", [line("11000003", "2", "551")], reason_code="DAMAGED", costObject="COST_CENTER:1120")
    text = json.dumps(bodies(p)) + sm.idoc_xml("STOCK_POSTING", p, CTX, {"code": "03", "items": items(p), "objectType": "STOCK_POSTING"})
    assert not any(word in text.lower() for word in ("password", "token", "secret", "authorization"))


# ================================================================ what the mapping refuses
def test_lines_sap_cannot_express_are_refused_with_a_reason():
    with pytest.raises(ValueError, match="movement type 999"):
        items(posting("TRANSFER", [line("11000002", "1", "999")]))
    with pytest.raises(ValueError, match="material 99999 is unknown"):
        items(posting("TRANSFER", [line("99999", "1", "311")]))
    with pytest.raises(ValueError, match="stock type CONSIGNMENT"):
        items(posting("TRANSFER", [line("11000002", "1", "311", ft="CONSIGNMENT")]))
    with pytest.raises(ValueError, match="needs a cost centre"):
        items(posting("SCRAP", [line("11000002", "1", "551")]))
    with pytest.raises(ValueError, match="needs a cost centre"):
        items({"reservation": "RSV-1", "plant": "1100", "storageLocation": "0001", "costObject": None, "lines": [{"material": "11000002", "qty": "1", "movement": "201"}]},
              "STOCK_RESERVATION")
    with pytest.raises(ValueError, match="no lines"):
        items(posting("TRANSFER", []))


# ================================================================ the connector against the loopback SAP mock
@pytest.fixture
def sap(monkeypatch):
    mock = SapMock()
    url = mock.start()
    monkeypatch.setenv("PIC_ERP_SAP_S4_URL", url)
    monkeypatch.setenv("PIC_ERP_SAP_S4_USER", "PIC_TECH")
    monkeypatch.setenv("PIC_ERP_SAP_S4_PASSWORD", "not-a-real-secret")
    monkeypatch.setenv("PIC_ERP_SAP_S4_SAP_CLIENT", "100")
    monkeypatch.setenv("PIC_ERP_SAP_S4_RETRIES", "1")
    monkeypatch.setattr("time.sleep", lambda s: None)
    yield mock
    mock.stop()


def message(kind, payload, key, object_type, ref):
    return IntegrationMessage(tenant_id=uuid.uuid4(), target_system="SAP_S4", message_type="STOCK_POSTING", idempotency_key=key, object_type=object_type, object_id=uuid.uuid4(),
                              object_ref=ref, payload=payload, payload_hash="x", status="PENDING", attempts=0)


def axn(who="inventory.controller", day=date(2027, 3, 31)):
    return ai_eval.rolled_back(ai_eval.scenario("AXN"), who, ai_eval._when(day, 10))


def dc330(s):
    return s.execute(select(Material).where(Material.number == "DC-330")).scalar_one()


def test_connector_maps_the_message_type_for_every_transport(sap, monkeypatch):
    connector = connectors.REGISTRY["SAP_S4"]
    assert connectors.maps("SAP_S4", "STOCK_POSTING") and "STOCK_POSTING" in connector.message_types          # OData
    monkeypatch.setenv("PIC_ERP_SAP_S4_TRANSPORT", "idoc")
    assert "STOCK_POSTING" in connector.message_types and sm.IDOC_TYPES["STOCK_POSTING"] == ("MBGMCR03", "MBGMCR")
    monkeypatch.delenv("PIC_ERP_SAP_S4_URL")
    monkeypatch.delenv("PIC_ERP_SAP_S4_TRANSPORT")
    assert connector.simulator and connectors.maps("SAP_S4", "STOCK_POSTING")                                  # simulator, as before


def test_a_posted_transfer_reaches_the_sap_mock_and_the_material_document_number_is_stored_as_erp_document(sap):
    with axn() as s:
        for plant in ("P100",):
            if s.execute(select(StorageLocation.id).where(StorageLocation.plant == plant, StorageLocation.code == "0002")).first() is None:
                s.add(StorageLocation(tenant_id=dc330(s).tenant_id, plant=plant, code="0002", name="Second location"))
                s.flush()
        posted = inventory.create_posting(s, posting_type="TRANSFER", plant="P100", submit=True,
                                          lines=[{"material": "DC-330", "qty": Decimal(1), "storage_location": "0001", "to_storage_location": "0002"}])
        assert posted.status == "POSTED" and posted.auto_posted
        entity, body = sap.created[-1]
        assert entity == "A_MaterialDocumentHeader" and body["GoodsMovementCode"] == "04" and body["MaterialDocumentHeaderText"] == f"STP|{posted.number}"
        assert body["ReferenceDocument"] == posted.number
        [item] = body["to_MaterialDocumentItem"]["results"]
        assert (item["Material"], item["Plant"], item["StorageLocation"], item["GoodsMovementType"], item["QuantityInEntryUnit"], item["EntryUnit"],
                item["IssuingOrReceivingStorageLoc"]) == ("DC-330", "P100", "0001", "311", "1.000", "EA", "0002")
        # PIC stores the number SAP answered with
        message_row = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == f"STP|{posted.number}")).scalar_one()
        assert message_row.status == "POSTED" and message_row.erp_doc_no and message_row.erp_doc_no.startswith("49000000")
        assert posted.erp_doc_no == message_row.erp_doc_no
        assert s.execute(select(AuditEvent).where(AuditEvent.object_id == posted.id, AuditEvent.action == "ERP_POSTED")).scalars().first() is not None
        # exactly once: processing the posted message again changes nothing, and SAP can be asked for the document by the PIC reference
        created = len(sap.created)
        integration.process(s, message_row)
        assert len(sap.created) == created
        assert connectors.REGISTRY["SAP_S4"].find(s, message_row).doc_no == message_row.erp_doc_no


def test_a_count_with_gains_and_losses_makes_two_material_documents_and_a_repost_finds_them(sap):
    count = {"inventory": "PHI-1001", "plant": "P100", "storageLocation": "0001", "grossMinor": 5, "companyCode": "1000",
             "lines": [{"material": "DC-330", "batch": "", "qty": "3.000", "movement": "701", "valueMinor": 3},
                       {"material": "DC-331", "batch": "", "qty": "-2.000", "movement": "702", "valueMinor": 2}]}
    connector = connectors.REGISTRY["SAP_S4"]
    with axn() as s:
        msg = message("STOCK_POSTING", count, "PHI|PHI-1001", "PHYSICAL_INVENTORY", "PHI-1001")
        assert connector.find(s, msg) is None
        number = connector.post(s, msg)
        assert len(number.split("/")) == 2 and all(n.startswith("49000000") for n in number.split("/"))
        codes = [b["GoodsMovementCode"] for e, b in sap.created if e == "A_MaterialDocumentHeader"][-2:]
        assert codes == ["03", "05"]
        created = len(sap.created)
        assert connector.find(s, msg).doc_no == number
        assert connector.post(s, msg) == number and len(sap.created) == created             # a retry after a lost answer creates nothing new


def test_a_second_document_missing_after_a_failure_is_created_without_repeating_the_first(sap):
    count = {"inventory": "PHI-1002", "plant": "P100", "storageLocation": "0001", "grossMinor": 5, "companyCode": "1000",
             "lines": [{"material": "DC-330", "batch": "", "qty": "3.000", "movement": "701", "valueMinor": 3},
                       {"material": "DC-331", "batch": "", "qty": "-2.000", "movement": "702", "valueMinor": 2}]}
    connector = connectors.REGISTRY["SAP_S4"]
    with axn() as s:
        msg = message("STOCK_POSTING", count, "PHI|PHI-1002", "PHYSICAL_INVENTORY", "PHI-1002")
        client = connector.client()
        specs = sm.stock_posting("PHYSICAL_INVENTORY", count, connector._ctx(s, msg), connector._stock_items(s, msg, connector._ctx(s, msg)))
        client.create(specs[0].service, specs[0].entity_set, specs[0].body)                   # SAP already holds the first document (code 03)
        assert connector.find(s, msg) is None                                                  # not all of them: the message still has work to do
        before = len([e for e, _ in sap.created if e == "A_MaterialDocumentHeader"])
        number = connector.post(s, msg)
        after = [b["GoodsMovementCode"] for e, b in sap.created if e == "A_MaterialDocumentHeader"]
        assert len(after) == before + 1 and after[-1] == "05" and len(number.split("/")) == 2


def test_scrap_without_a_cost_centre_is_rejected_and_the_configured_default_makes_it_postable(sap, monkeypatch):
    scrap = {"posting": "STP-1003", "type": "SCRAP", "plant": "P100", "postingDate": "2027-03-31", "grossMinor": 5, "reasonCode": "DAMAGED", "reason": "x", "companyCode": "1000",
             "lines": [{"material": "DC-330", "batch": "", "qty": "1.000", "movement": "551", "fromPlant": "P100", "fromStorageLocation": "0001", "fromStockType": "UNRESTRICTED"}]}
    connector = connectors.REGISTRY["SAP_S4"]
    with axn() as s:
        msg = message("STOCK_POSTING", scrap, "STP|STP-1003", "STOCK_POSTING", "STP-1003")
        with pytest.raises(connectors.ConnectorRejected, match="needs a cost centre"):
            connector.post(s, msg)
        monkeypatch.setenv("PIC_ERP_SAP_S4_SCRAP_COST_CENTER", "4100")
        monkeypatch.setenv("PIC_ERP_SAP_S4_REASON_MAP", "DAMAGED=0007")
        assert connector.post(s, msg)
        [item] = sap.created[-1][1]["to_MaterialDocumentItem"]["results"]
        assert item["CostCenter"] == "4100" and item["GoodsMovementReasonCode"] == "0007" and item["GoodsMovementType"] == "551"


def test_reversal_is_not_mapped_and_says_so(sap):
    msg = message("STOCK_POSTING", {"posting": "STP-1", "plant": "P100", "reversalOf": "4900000001", "lines": []}, "STP|STP-1", "STOCK_POSTING", "STP-1")
    with axn() as s, pytest.raises(connectors.ConnectorRejected, match="never reverses"):
        connectors.REGISTRY["SAP_S4"].post(s, msg)


def test_idoc_over_http_and_to_a_file_port(sap, monkeypatch, tmp_path):
    transfer = {"posting": "STP-1004", "type": "TRANSFER", "plant": "P100", "postingDate": "2027-03-31", "grossMinor": 5, "companyCode": "1000",
                "lines": [{"material": "DC-330", "batch": "", "qty": "2.000", "movement": "311", "fromPlant": "P100", "fromStorageLocation": "0001", "fromStockType": "UNRESTRICTED",
                           "toPlant": "P100", "toStorageLocation": "0002", "toStockType": "UNRESTRICTED"}]}
    connector = connectors.REGISTRY["SAP_S4"]
    monkeypatch.setenv("PIC_ERP_SAP_S4_TRANSPORT", "idoc")
    with axn() as s:
        msg = message("STOCK_POSTING", transfer, "STP|STP-1004", "STOCK_POSTING", "STP-1004")
        assert connector.post(s, msg) == "0000000000000001"
        xml = sap.idocs[0]
        assert "<IDOCTYP>MBGMCR03</IDOCTYP>" in xml and "<GM_CODE>04</GM_CODE>" in xml and "<MOVE_TYPE>311</MOVE_TYPE>" in xml and "<MOVE_STLOC>0002</MOVE_STLOC>" in xml
        assert "<ARCKEY>STP|STP-1004</ARCKEY>" in xml
        monkeypatch.setenv("PIC_ERP_SAP_S4_TRANSPORT", "idoc-file")
        monkeypatch.setenv("PIC_ERP_SAP_S4_IDOC_DIR", str(tmp_path))
        assert connector.find(s, msg) is None
        ref = connectors.reference("STP|STP-1004", 25)
        assert connector.post(s, msg) == ref and (tmp_path / f"{sap_odata.safe_name(ref)}.xml").exists()
        assert connector.find(s, msg).doc_no == ref


def test_the_simulator_still_posts_stock_postings_without_any_configuration(monkeypatch):
    for key in ("URL", "IDOC_DIR", "TRANSPORT"):
        monkeypatch.delenv(f"PIC_ERP_SAP_S4_{key}", raising=False)
    with axn() as s:
        posted = inventory.create_posting(s, posting_type="BLOCK", plant="P100", submit=True, reason_code="QUALITY_DOUBT", reason="Supplier advised a possible out-of-spec lot",
                                          lines=[{"material": "DC-330", "qty": Decimal(1), "storage_location": "0001"}])
        assert posted.status == "POSTED" and posted.erp_doc_no and posted.erp_doc_no.startswith("49000")
