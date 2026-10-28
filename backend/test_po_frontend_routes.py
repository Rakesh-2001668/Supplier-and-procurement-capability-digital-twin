import requests

ROUTES = [
    "http://localhost:3000/purchase-orders",
    "http://localhost:3000/purchase-orders/pending",
    "http://localhost:3000/purchase-orders/create",
    "http://localhost:3000/purchase-orders/templates"
]

def test_routes():
    all_ok = True
    for url in ROUTES:
        try:
            r = requests.get(url, timeout=30)
            print(f"Route: {url} -> Status: {r.status_code}")
            if r.status_code != 200:
                all_ok = False
        except Exception as e:
            print(f"Route: {url} -> Failed with exception: {e}")
            all_ok = False
            
    if all_ok:
        print("\nALL FRONTEND PURCHASE ORDER ROUTES RETURNED HTTP 200 OK!")
    else:
        print("\nSOME ROUTES FAILED!")

if __name__ == "__main__":
    test_routes()
