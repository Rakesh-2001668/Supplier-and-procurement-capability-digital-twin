"""Document numbers from suppliers and ERPs contain slashes (THT/27-28/0311): the generic document endpoints behind every object page
(approvals, files, process, lineage, audit) must resolve them, whether the slash arrives plain or as %2F."""
from urllib.parse import quote


def _slash_invoice(client, headers):
    items = client.get("/v1/invoices?limit=200", headers=headers).json()["items"]
    numbers = [i["number"] for i in items if "/" in i["number"]]
    assert numbers, "the seeded signature tenant has invoices numbered like THT/27-28/0311"
    return numbers[0]


def test_object_page_endpoints_resolve_a_reference_that_contains_slashes(client, login):
    headers = login("admin")
    number = _slash_invoice(client, headers)
    for encoding in (lambda n: quote(n, safe=""), lambda n: n):
        ref = encoding(number)
        for path in (f"/v1/documents/INVOICE/{ref}/approvals", f"/v1/documents/INVOICE/{ref}/files",
                     f"/v1/documents/INVOICE/{ref}/process", f"/v1/lineage/INVOICE/{ref}", f"/v1/audit/INVOICE/{ref}"):
            r = client.get(path, headers=headers)
            assert r.status_code == 200, (path, r.status_code, r.text[:200])


def test_an_unknown_reference_with_slashes_is_a_clean_404(client, login):
    headers = login("admin")
    r = client.get("/v1/lineage/INVOICE/NO/SUCH/0001", headers=headers)
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
    assert client.get("/v1/audit/verify", headers=headers).status_code == 200  # the fixed route is not swallowed by the path route
