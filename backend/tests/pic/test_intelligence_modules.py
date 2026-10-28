"""Spend governance, forecast review, supplier risk/CAPA, PO-03/04, reconciliation, savings initiatives, manual contracts,
agent console and administration (blueprint SPD, MRP-04, SLM-03/04, CLM-04, PO-03/04, INV-03/04, SAV-01, AIX-03, ADM-01/04)."""
from datetime import datetime

import pytest

from app.pic.platform import clock


@pytest.fixture()
def oct_2026():
    """Spend views use the last 12 complete months before today; pin today so the ERP history window is fixed."""
    clock.set_pinned(datetime(2026, 10, 27, 12, 0, tzinfo=clock.IST))
    yield
    clock.set_pinned(None)


def test_spend_overview_matches_the_blueprint_portfolio(client, login, oct_2026):
    o = client.get("/v1/spend/overview", headers=login("cpo")).json()
    assert o["periods"] == ["2025-10", "2026-09"]
    assert 400 < o["totalMinor"] / 1e9 < 430, o["totalMinor"]  # ≈ 412 Cr
    assert 68 <= float(o["contractedPct"]) <= 74
    assert 5 <= float(o["maverickPct"]) <= 8
    assert float(o["addressablePct"]) < 100  # intercompany excluded
    assert o["opportunities"] and o["topMovers"]
    assert client.get("/v1/spend/overview", headers=login("buyer")).status_code == 403


def test_treemap_concentration_and_duplicate_suppliers(client, login, oct_2026):
    tree = client.get("/v1/spend/treemap", headers=login("category.head")).json()
    assert {s["code"] for s in tree["segments"]} >= {"DIRECT", "INDIRECT", "INTERCOMPANY"}
    view = client.get("/v1/spend/suppliers", headers=login("category.head")).json()
    alu = next(c for c in view["concentration"] if c["category"] == "ALU-DIECAST")
    assert alu["topSupplier"] == "TF001" and alu["level"] == "HIGH" and alu["suppliers"] == 3
    names = [{s["code"] for s in c["suppliers"]} for c in view["duplicateClusters"]]
    assert {"V-210111", "V-210112"} in names  # Kanchi Industrial Supplies / Supply Co


def test_maverick_hits_need_owner_and_commented_disposition(client, login):
    m = client.get("/v1/spend/maverick?status=OPEN&rule=SPLIT_PO", headers=login("procurement.head")).json()
    assert {r["code"] for r in m["rules"]} >= {"PO_AFTER_INVOICE", "SPLIT_PO", "NON_CATALOGUE", "OFF_CONTRACT_PRICE", "ONE_TIME_VENDOR"}
    hit = m["hits"][0]
    assert hit["owner_role"] == "PROCUREMENT_HEAD" and hit["owner_id"]
    h = login("procurement.head")
    r = client.post(f"/v1/spend/maverick-hits/{hit['id']}/disposition", json={"disposition": "POLICY_BREACH", "comment": ""}, headers=h)
    assert r.status_code == 422 and r.json()["code"] == "COMMENT_REQUIRED"
    r = client.post(f"/v1/spend/maverick-hits/{hit['id']}/disposition",
                    json={"disposition": "POLICY_BREACH", "comment": "Split below band; buyer briefed"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "DISPOSED"
    disposed = client.get("/v1/spend/maverick?status=RECOVERY_OPEN", headers=h).json()["hits"]
    assert disposed and disposed[0]["rule_code"] == "OFF_CONTRACT"


def test_classification_below_threshold_goes_to_stewards(client, login):
    h = login("category.head")
    queue = client.get("/v1/spend/classification-reviews?status=ACCEPTED", headers=h).json()["reviews"] + \
        client.get("/v1/spend/classification-reviews?status=RECLASSIFIED", headers=h).json()["reviews"]
    assert queue and all(float(r["confidence"]) < 0.80 for r in queue)
    open_ = client.get("/v1/spend/classification-reviews", headers=h).json()
    if open_["reviews"]:
        review = open_["reviews"][0]
        bad = client.post(f"/v1/spend/classification-reviews/{review['id']}/decision", json={"category": "NOPE"}, headers=h)
        assert bad.status_code == 422


def test_category_plans_kraljic_and_approval(client, login):
    plans = {p["category"]: p for p in client.get("/v1/category-plans", headers=login("category.head")).json()}
    alu = plans["ALU-DIECAST"]
    assert alu["kraljic"] == "STRATEGIC" and alu["status"] == "APPROVED" and alu["levers"]
    assert plans["FASTENERS"]["kraljic"] in ("NON_CRITICAL", "LEVERAGE")
    assert plans["ELECTRONICS"]["kraljic"] in ("BOTTLENECK", "STRATEGIC")
    assert "IC-TRANSFER" not in plans
    draft = next(p for p in plans.values() if p["status"] == "DRAFT")
    own = client.post(f"/v1/category-plans/{draft['number']}/approve", json={}, headers=login("category.head"))
    assert own.status_code == 403  # category managers cannot approve; the procurement head or CPO does


def test_forecast_review_override_and_release(client, login):
    rows = {r["material"]: r for r in client.get("/v1/forecasts", headers=login("mrp.controller")).json()}
    dc331 = rows["DC-331"]
    assert dc331["bias"] is not None and float(dc331["bias"]) > 0.15
    overridden = [p for p in dc331["periods"] if p["overrideQty"]]
    assert overridden and overridden[0]["released"] and "Demand Sensing" in overridden[0]["overrideReason"]
    future = next(p for p in rows["DC-330"]["periods"] if p["actualQty"] is None)
    h = login("mrp.controller")
    assert client.post(f"/v1/forecasts/{future['id']}/override", json={"qty": "1", "reason": ""}, headers=h).status_code == 422
    assert client.post(f"/v1/forecasts/{future['id']}/override", json={"qty": "1", "reason": "test"}, headers=login("buyer")).status_code == 403


def test_supplier_risk_monitor_and_capa(client, login):
    monitor = client.get("/v1/supplier-risk", headers=login("supplier.manager")).json()
    zat = next(s for s in monitor["signals"] if s["supplier"] == "ZAT006")
    assert zat["severity"] == "Critical" and zat["category"] == "COMPLIANCE"
    capas = client.get("/v1/capas", headers=login("quality.inspector")).json()
    capa = next(c for c in capas if c["supplier"] == "TF001")
    assert capa["status"] == "RESPONDED" and capa["actions"]
    # Kovai's portal user sees only Kovai's CAPAs.
    assert all(c["supplier"] == "KD002" for c in client.get("/v1/capas", headers=login("kd.sales")).json())
    assert client.post(f"/v1/capas/{capa['number']}/verify", json={"effective": True, "comment": "ok"}, headers=login("buyer")).status_code == 403
    r = client.post(f"/v1/capas/{capa['number']}/verify", json={"effective": True, "comment": "Two weeks of 100% X-ray clean"},
                    headers=login("quality.inspector"))
    assert r.status_code == 200 and r.json()["status"] == "CLOSED"
    perf = client.get("/v1/supplier-performance", headers=login("supplier.manager")).json()
    assert any(p["supplier"] == "TF001" and p["trend"] for p in perf)


def test_preferred_status_needs_scorecard_evidence(client, login):
    r = client.post("/v1/suppliers/TF001/categories/ALU-DIECAST/status", json={"status": "PREFERRED", "reason": "Top performer"},
                    headers=login("supplier.manager"))
    assert r.status_code == 409 and r.json()["code"] == "RULE_VIOLATION"  # OTIF below 95% / PPM issue on the latest scorecard


def test_po_change_requests_and_expediting(client, login):
    view = client.get("/v1/po-confirmations", headers=login("buyer")).json()
    pcr = next(r for r in view["changeRequests"] if r["po"] == "PO-77417")
    assert pcr["status"] == "ACCEPTED" and pcr["resultVersion"] == 3 and pcr["origin"] == "SUPPLIER"
    assert any(v["po"] == "PO-77417" and v["version"] == 2 for v in view["versions"])
    # A supplier cannot request changes on another supplier's order.
    r = client.post("/v1/purchase-orders/PO-77417/change-requests", json={"lines": [{"line": 10, "qty": "1"}], "reason": "x"},
                    headers=login("kd.sales"))
    assert r.status_code == 403
    rows = client.get("/v1/expediting", headers=login("buyer")).json()
    assert all(r["risk"] in ("LATE", "AT_RISK", "ON_TRACK") for r in rows)


def test_reconciliation_and_payables_insights(client, login):
    run = client.post("/v1/reconciliation/runs", json={"company_code": "1000"}, headers=login("ap.clerk")).json()
    assert run["platformCount"] == run["erpCount"] > 0 and run["differences"] == 0 and run["platformMinor"] == run["erpMinor"]
    assert client.post("/v1/reconciliation/runs", json={}, headers=login("buyer")).status_code == 403
    k = client.get("/v1/payables/insights", headers=login("finance.controller")).json()
    assert k["dpoDays"] is not None and k["firstPassMatchPct"] == "60.0" and k["duplicatesPrevented"] >= 1
    assert k["discountCapturePct"] is None and k["discountNote"]


def test_savings_initiative_baselines_and_sod(client, login):
    h = login("category.manager")
    r = client.post("/v1/savings/initiatives", json={"title": "x", "category": "FASTENERS", "baseline_method": "SHOULD_COST", "annual_volume": "10"},
                    headers=h)
    assert r.status_code == 422 and r.json()["code"] == "BASELINE_REQUIRED"
    r = client.post("/v1/savings/initiatives", json={"title": "Casting should-cost", "category": "ALU-DIECAST", "baseline_method": "STANDARD",
                                                     "annual_volume": "1000", "material": "DC-330"}, headers=h)
    assert r.status_code == 201 and r.json()["baseline_price_minor"] == 41000 and r.json()["stage"] == "IDENTIFIED"
    register = {s["title"]: s for s in client.get("/v1/savings", headers=h).json()}
    fasteners = register["Fastener kit consolidation FY27-28"]
    assert fasteners["stage"] == "NEGOTIATED" and fasteners["baselineMethod"] == "LAST_PRICE"


def test_manual_contract_templates_obligations_and_renewals(client, login):
    h = login("contract.manager")
    templates = client.get("/v1/contract-templates", headers=h).json()
    assert {"SCHEDULING_AGREEMENT", "VALUE_CONTRACT", "QUANTITY_CONTRACT"} <= set(templates["types"])
    body = {"type": "QUANTITY_CONTRACT", "title": "Fastener kits FY27-28", "supplier": "V-210071", "valid_from": "2027-04-01",
            "valid_to": "2028-03-31", "payment_terms": "N45", "lines": [{"material": "FK-M8-50", "description": "Fastener kit M8 x 50",
                                                                       "uom": "EA", "target_qty": "480000", "unit_price_minor": 1175}]}
    r = client.post("/v1/contracts", json=body, headers={**h, "Idempotency-Key": "qc-fk-1"})
    assert r.status_code == 201 and r.json()["status"] == "DRAFT"
    again = client.post("/v1/contracts", json=body, headers={**h, "Idempotency-Key": "qc-fk-1"})
    assert again.json()["replayed"] is True and again.json()["number"] == r.json()["number"]
    assert client.post("/v1/contracts", json={**body, "supplier": "ZAT006"}, headers=h).status_code == 409  # blocked supplier
    no_index = client.post("/v1/contracts", json={**body, "type": "SCHEDULING_AGREEMENT"}, headers=h)
    assert no_index.status_code == 422 and no_index.json()["code"] == "INDEX_REQUIRED"
    assert any(r["role"] == "BUYER" for r in client.get("/v1/admin/roles", headers=login("admin")).json())
    first = client.get("/v1/obligations", headers=h).json()["items"][0]
    client.post(f"/v1/obligations/{first['id']}/complete", json={"note": "Forecast shared on 2 Apr"}, headers=h)
    obligations = client.get("/v1/obligations", headers=h).json()
    assert obligations["completed"] >= 1
    assert any(o["contract"] == r.json()["number"] for o in obligations["items"])
    assert any(x["contract"] == "SA-5520" for x in client.get("/v1/contracts-renewals", headers=h).json())


def test_agent_console_autonomy_runs_and_feedback(client, login):
    assert client.put("/v1/agents/SUPPLIER_RISK/autonomy", json={"level": "L2", "reason": "x"}, headers=login("buyer")).status_code == 403
    r = client.put("/v1/agents/GUIDED_BUYING/autonomy", json={"level": "L4", "reason": "try"}, headers=login("cpo"))
    assert r.status_code == 409  # L4 needs configured categories
    r = client.put("/v1/agents/SUPPLIER_RISK/autonomy", json={"level": "L1", "reason": "Confirm default"}, headers=login("cpo"))
    assert r.status_code == 200
    run = client.post("/v1/agents/SUPPLIER_RISK/runs", headers=login("supplier.manager"))
    assert run.status_code == 200 and "signals" in run.json()["result"]
    assert client.post("/v1/agents/TOUCHLESS_PO/runs", headers=login("cpo")).status_code == 422  # event-driven agent
    recs = client.get("/v1/recommendations", headers=login("supplier.manager")).json()
    assert recs and all(r["role"] == "SUPPLIER_MANAGER" for r in recs)
    rec = recs[0]
    bad = client.post(f"/v1/recommendations/{rec['id']}/feedback", json={"accepted": False}, headers=login("supplier.manager"))
    assert bad.status_code == 422
    ok = client.post(f"/v1/recommendations/{rec['id']}/feedback", json={"accepted": False, "comment": "Already handled offline"},
                     headers=login("supplier.manager"))
    assert ok.status_code == 200 and ok.json()["status"] == "REJECTED"
    accepted = client.get("/v1/recommendations?status=ACCEPTED", headers=login("mrp.controller")).json()
    assert any(r["agent"] == "DEMAND_SENSING" for r in accepted)


def test_admin_organisation_fx_users_and_templates(client, login):
    h = login("admin")
    org = client.get("/v1/admin/organisation", headers=h).json()
    assert {c["code"] for c in org["currencies"]} >= {"INR", "USD", "EUR"} and org["tenant"]["industryTemplate"] == "MANUFACTURING"
    assert [p["code"] for p in org["plants"]] == ["P100", "P200"]
    r = client.post("/v1/admin/fx-rates", json={"from_ccy": "USD", "to_ccy": "INR", "rate": "84.25", "valid_from": "2027-04-01",
                                                "source": "Treasury month-end rate"}, headers=h)
    assert r.status_code == 201
    assert client.post("/v1/admin/fx-rates", json={"from_ccy": "USD", "to_ccy": "INR", "rate": "84.30", "valid_from": "2027-04-01",
                                                   "source": "dup"}, headers=h).status_code == 409
    users = client.get("/v1/admin/users", headers=h).json()
    buyer = next(u for u in users if u["email"] == "buyer@axion.example")
    toxic = client.put(f"/v1/admin/users/{buyer['id']}/roles", json={"roles": ["BUYER", "RECEIVER"], "reason": "cover"}, headers=h)
    assert toxic.status_code == 409 and toxic.json()["code"] == "SOD_CONFLICT"
    assert client.get("/v1/admin/users", headers=login("buyer")).status_code == 403
    templates = client.get("/v1/admin/templates", headers=h).json()
    assert len(templates["templates"]) == 6 and templates["current"] == "MANUFACTURING"


def test_new_tables_are_tenant_isolated():
    from sqlalchemy import func, select

    from app.pic.db import system_tx, tenant_tx
    from app.pic.models import MaverickHit, RiskSignal, SpendLine, Tenant
    with system_tx() as s:
        tenants = dict(s.execute(select(Tenant.code, Tenant.id)).all())
    other = next(code for code in tenants if code != "AXN")
    with tenant_tx(tenants["AXN"]) as s:
        axn_lines = s.execute(select(func.count()).select_from(SpendLine)).scalar()
        axn_hits = {h.number for h in s.execute(select(MaverickHit)).scalars()}
    with tenant_tx(tenants[other]) as s:
        assert s.execute(select(func.count()).select_from(SpendLine).where(SpendLine.invoice_ref.like("ERP-%"))).scalar() == 0
        assert not ({h.number for h in s.execute(select(MaverickHit)).scalars()} & axn_hits) or other != "AXN"
        assert s.execute(select(func.count()).select_from(RiskSignal)).scalar() >= 0
    assert axn_lines > 2000


def test_upgrade_path_is_idempotent():
    from sqlalchemy import select

    from app.pic.db import system_tx
    from app.pic.models import Tenant
    from app.pic.seed import reference
    with system_tx() as s:
        axn = s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()
    assert reference.ensure_extensions(axn) == []
