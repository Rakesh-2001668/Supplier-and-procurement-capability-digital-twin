import requests

BASE_URL = "http://127.0.0.1:8080/api/v1/procurement"

def test_endpoints():
    print("Testing RFQ Overview...")
    r1 = requests.get(f"{BASE_URL}/rfqs/overview")
    print("Overview:", r1.status_code, r1.json())
    assert r1.status_code == 200

    print("\nTesting RFQs List...")
    r2 = requests.get(f"{BASE_URL}/rfqs/list")
    print("List count:", len(r2.json()), [x["id"] for x in r2.json()])
    assert r2.status_code == 200

    print("\nTesting RFQ Bids for RFQ-2026-092...")
    r3 = requests.get(f"{BASE_URL}/rfqs/RFQ-2026-092/bids")
    data3 = r3.json()
    print("Bids count:", len(data3["bids"]), "Top winner:", data3["bids"][0]["supplier_name"], "MCDA:", data3["bids"][0]["mcda_score"])
    assert r3.status_code == 200

    print("\nTesting RFQ Awards List...")
    r4 = requests.get(f"{BASE_URL}/rfqs/awards/list")
    print("Awards count:", len(r4.json()))
    assert r4.status_code == 200

    print("\nTesting RFQ Analytics...")
    r5 = requests.get(f"{BASE_URL}/rfqs/analytics")
    print("Analytics categories:", len(r5.json()["category_performance"]))
    assert r5.status_code == 200

    print("\nALL RFQ BACKEND ENDPOINTS VERIFIED SUCCESSFULLY!")

if __name__ == "__main__":
    test_endpoints()
