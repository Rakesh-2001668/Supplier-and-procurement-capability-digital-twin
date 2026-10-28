import requests
import json

BASE_URL = "http://127.0.0.1:8080/api/v1/procurement"

def test_endpoints():
    print("Testing GET /purchase-orders/overview ...")
    r = requests.get(f"{BASE_URL}/purchase-orders/overview")
    print(f"Status: {r.status_code}")
    print(json.dumps(r.json(), indent=2))
    assert r.status_code == 200

    print("\nTesting GET /purchase-orders/list ...")
    r = requests.get(f"{BASE_URL}/purchase-orders/list")
    print(f"Status: {r.status_code}, Count: {r.json().get('count')}")
    assert r.status_code == 200
    pos = r.json().get("purchase_orders", [])
    if pos:
        print(f"First PO: {pos[0]['po_number']} - {pos[0]['status']} - ${pos[0]['total_amount']}")

    print("\nTesting GET /purchase-orders/approvals/pending ...")
    r = requests.get(f"{BASE_URL}/purchase-orders/approvals/pending")
    print(f"Status: {r.status_code}, Pending Count: {r.json().get('pending_count')}")
    assert r.status_code == 200

    print("\nTesting GET /purchase-orders/fulfillment/PO-2026-6488 ...")
    r = requests.get(f"{BASE_URL}/purchase-orders/fulfillment/PO-2026-6488")
    print(f"Status: {r.status_code}")
    assert r.status_code == 200
    dossier = r.json().get("fulfillment_dossier", {})
    print(f"PO: {dossier.get('po_number')} - Tier: {dossier.get('approval_tier')} - Milestones: {len(dossier.get('milestones', []))}")

    print("\nALL BACKEND ENDPOINTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_endpoints()
