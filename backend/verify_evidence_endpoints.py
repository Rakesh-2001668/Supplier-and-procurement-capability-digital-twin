import requests
import json

BASE = "http://127.0.0.1:8080/api/v1/evidence"

def test_endpoints():
    print("Testing GET /overview...")
    r = requests.get(f"{BASE}/overview")
    assert r.status_code == 200, f"Overview failed: {r.status_code} {r.text}"
    print("[OK] Overview OK")

    print("Testing GET /conflicts...")
    r = requests.get(f"{BASE}/conflicts")
    assert r.status_code == 200, f"Conflicts failed: {r.status_code} {r.text}"
    conflicts_data = r.json()
    print(f"[OK] Conflicts OK: {conflicts_data['total_conflicts']} conflicts, open={conflicts_data['open_count']}")

    print("Testing GET /conflicts/CONF-2024-001...")
    r = requests.get(f"{BASE}/conflicts/CONF-2024-001")
    assert r.status_code == 200, f"Get conflict failed: {r.status_code} {r.text}"
    print(f"[OK] Get conflict OK: {r.json()['conflict']['conflict_type']}")

    print("Testing POST /conflicts/CONF-2024-001/resolve...")
    r = requests.post(f"{BASE}/conflicts/CONF-2024-001/resolve", json={
        "resolution_action": "ACCEPT_DOCUMENT_VALUE",
        "notes": "Verified against notarized commercial register excerpt.",
        "resolver_name": "Chief Compliance Officer"
    })
    assert r.status_code == 200, f"Resolve conflict failed: {r.status_code} {r.text}"
    print(f"[OK] Resolve conflict OK: status={r.json()['conflict']['status']}")

    print("Testing POST /integrity/batch-check...")
    r = requests.post(f"{BASE}/integrity/batch-check")
    assert r.status_code == 200, f"Integrity batch check failed: {r.status_code} {r.text}"
    integrity_data = r.json()
    print(f"[OK] Integrity batch check OK: score={integrity_data['overall_integrity_score']}%, checked={integrity_data['total_documents_checked']}")

    print("Testing GET /audit-trail...")
    r = requests.get(f"{BASE}/audit-trail")
    assert r.status_code == 200, f"Audit trail failed: {r.status_code} {r.text}"
    audit_data = r.json()
    print(f"[OK] Audit trail OK: {audit_data['total_events']} events, total_kpi={audit_data['kpis']['total_audit_events']}")

    print("\nALL BACKEND EVIDENCE VERIFICATION & CONFLICT ENDPOINTS PASSED!\n")

if __name__ == "__main__":
    test_endpoints()
