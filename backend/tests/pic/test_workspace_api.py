"""APIs behind the workspace screens: worklists, pagination, dashboard, Copilot, hardening."""


def test_lists_are_paginated(client, login):
    headers = login("buyer")
    first = client.get("/v1/purchase-orders?limit=2", headers=headers).json()
    assert len(first["items"]) == 2 and first["nextCursor"]
    numbers, page = [p["number"] for p in first["items"]], first
    while page["nextCursor"]:
        page = client.get(f"/v1/purchase-orders?limit=2&cursor={page['nextCursor']}", headers=headers).json()
        numbers += [p["number"] for p in page["items"]]
    assert len(numbers) == len(set(numbers))  # no row repeated across pages
    assert {"PO-77395", "PO-77410", "PO-77411", "PO-77412", "PO-77416"} <= set(numbers)
    assert client.get("/v1/purchase-orders?cursor=garbage", headers=headers).status_code == 400


def test_supplier_lists_only_show_own_documents(client, login):
    pos = client.get("/v1/purchase-orders", headers=login("tf.sales")).json()["items"]
    assert pos and {p["supplier_code"] for p in pos} == {"TF001"}
    invoices = client.get("/v1/invoices", headers=login("kd.sales")).json()["items"]
    assert invoices and {i["supplier_code"] for i in invoices} == {"KD002"}
    events = client.get("/v1/sourcing/events", headers=login("sla.sales")).json()["items"]
    assert [e["number"] for e in events] == ["RFQ-2231"]


def test_worklists_exist_for_every_flow(client, login):
    headers = login("admin")
    for path in ["/v1/requisitions", "/v1/mrp/runs", "/v1/planned-orders", "/v1/sourcing/events", "/v1/contracts", "/v1/asns",
                 "/v1/goods-receipts", "/v1/inspection-lots?status=", "/v1/service-entries", "/v1/invoices", "/v1/suppliers",
                 "/v1/bank-changes", "/v1/materials", "/v1/materials/requests", "/v1/processes", "/v1/integration/messages", "/v1/audit",
                 "/v1/reference"]:
        r = client.get(path, headers=headers)
        assert r.status_code == 200, (path, r.text)


def test_dashboard_kpis(client, login):
    k = client.get("/v1/dashboard", headers=login("cpo")).json()
    # SV-0412 (0.99 Cr, signature case) plus the fastener initiative SV-0413 (0.036 Cr).
    assert k["savings"]["negotiatedCr"] == "1.03"
    assert k["purchasing"]["touchlessPct"] is not None
    # First pass: HTS/1107, HTS/1188, INV-TF-9031 yes; INV-TF-8812 (credit note) and KD/2702-118 (price) no; the rejected duplicate never matched.
    assert k["payables"]["firstPassMatchPct"] == "60.0"
    assert k["activity"]


def test_copilot_answer_contract(client, login):
    a = client.post("/v1/copilot/ask", json={"question": "What is the status of PO-77410?"}, headers=login("buyer")).json()
    assert set(a) == {"answer", "evidence", "confidence", "explanation", "recommendedAction", "permission"}
    assert "PO-77410" in a["answer"] and a["evidence"][0]["ref"] == "PO-77410"
    assert a["recommendedAction"]["deepLink"] == "/pic/purchase-orders/PO-77410"
    s = client.post("/v1/copilot/ask", json={"question": "show savings"}, headers=login("cpo")).json()
    assert "SV-0412" in s["answer"]
    # A supplier cannot read another supplier's document through the Copilot.
    blocked = client.post("/v1/copilot/ask", json={"question": "status of PO-77410"}, headers=login("kd.sales")).json()
    assert "not found or is not visible" in blocked["answer"]


def test_request_id_and_readiness(client, login):
    r = client.get("/v1/me", headers={**login("buyer"), "X-Request-ID": "trace-123"})
    assert r.headers["X-Request-ID"] == "trace-123" and r.headers["X-Frame-Options"] == "DENY"
    problem = client.get("/v1/tasks", headers={"X-Request-ID": "trace-456"}).json()
    assert problem["traceId"] == "trace-456"
    assert client.get("/readyz").json()["status"] == "ready"


def test_failed_sign_ins_are_throttled(client):
    from app.pic.platform import http
    http._login_attempts.clear()
    for _ in range(10):
        assert client.post("/v1/auth/token", json={"tenant": "AXN", "email": "buyer@axion.example", "password": "wrong"}).status_code == 401
    r = client.post("/v1/auth/token", json={"tenant": "AXN", "email": "buyer@axion.example", "password": "wrong"})
    assert r.status_code == 429 and r.headers["Retry-After"] == "300"
    http._login_attempts.clear()
