import requests
import json
import time

API_BASE = "http://127.0.0.1:8080/api/v1/evidence"
FRONTEND_BASE = "http://localhost:3000"

def test_evidence_verification_and_conflicts():
    print("==================================================")
    print("AI EVIDENCE DEEP VERIFICATION & CONFLICT RESOLUTION")
    print("==================================================")

    # 1. Overview
    print("\n[1] Checking GET /api/v1/evidence/overview...")
    r = requests.get(f"{API_BASE}/overview")
    assert r.status_code == 200, f"Overview failed: {r.status_code}"
    overview = r.json()
    print(f"    [PASS] Total Docs: {overview['kpis']['total_documents']}, Verified: {overview['kpis']['verified_count']}")

    # 2. Documents
    print("\n[2] Checking GET /api/v1/evidence/documents...")
    r = requests.get(f"{API_BASE}/documents")
    assert r.status_code == 200, f"Documents list failed: {r.status_code}"
    docs = r.json()["documents"]
    print(f"    [PASS] Retrieved {len(docs)} vault documents.")

    # 3. Conflicts List
    print("\n[3] Checking GET /api/v1/evidence/conflicts...")
    r = requests.get(f"{API_BASE}/conflicts")
    assert r.status_code == 200, f"Conflicts list failed: {r.status_code}"
    conflicts_data = r.json()
    print(f"    [PASS] Total Conflicts: {conflicts_data['total_conflicts']} (Open: {conflicts_data['open_count']}, In Review: {conflicts_data['in_review_count']}, High Risk: {conflicts_data['high_risk_count']})")

    # 4. Conflict Detail
    print("\n[4] Checking GET /api/v1/evidence/conflicts/CONF-2024-001...")
    r = requests.get(f"{API_BASE}/conflicts/CONF-2024-001")
    assert r.status_code == 200, f"Conflict detail failed: {r.status_code}"
    c1 = r.json()["conflict"]
    print(f"    [PASS] Found: {c1['conflict_type']} for {c1['supplier_name']}")

    # 5. Resolve Conflict
    print("\n[5] Checking POST /api/v1/evidence/conflicts/CONF-2024-001/resolve...")
    r = requests.post(f"{API_BASE}/conflicts/CONF-2024-001/resolve", json={
        "resolution_action": "ACCEPT_DOCUMENT_VALUE",
        "notes": "Verified against registered commercial court excerpt HRB 99281.",
        "resolver_name": "Chief Compliance Officer"
    })
    assert r.status_code == 200, f"Resolve conflict failed: {r.status_code}"
    print(f"    [PASS] Resolved successfully: status={r.json()['conflict']['status']}")

    # 6. Escalate Conflict
    print("\n[6] Checking POST /api/v1/evidence/conflicts/CONF-2024-003/escalate...")
    r = requests.post(f"{API_BASE}/conflicts/CONF-2024-003/escalate", json={
        "reason": "Dodd-Frank 1502 smelter lapse requires Legal & Defense Trade advisory.",
        "escalated_to": "Defense & Aerospace Compliance Oversight Committee",
        "escalator_name": "Senior ESG Auditor"
    })
    assert r.status_code == 200, f"Escalate conflict failed: {r.status_code}"
    print(f"    [PASS] Escalated successfully: status={r.json()['conflict']['status']}")

    # 7. Batch Cryptographic Integrity Check
    print("\n[7] Checking POST /api/v1/evidence/integrity/batch-check...")
    r = requests.post(f"{API_BASE}/integrity/batch-check")
    assert r.status_code == 200, f"Integrity batch check failed: {r.status_code}"
    integ = r.json()
    print(f"    [PASS] Integrity Score: {integ['overall_integrity_score']}%, Checked: {integ['total_documents_checked']}, Passed: {integ['passed_count']}, Tamper Count: {integ['tampering_detected_count']}")

    # 8. Single Document Tamper Check
    print("\n[8] Checking POST /api/v1/evidence/tamper-check/DOC-EVID-001...")
    r = requests.post(f"{API_BASE}/tamper-check/DOC-EVID-001")
    assert r.status_code == 200, f"Tamper check failed: {r.status_code}"
    tc = r.json()
    print(f"    [PASS] Single Doc Tamper Status: {tc['integrity_status']}, Valid: {tc['is_tamper_free']}")

    # 9. Single Document Verify
    print("\n[9] Checking POST /api/v1/evidence/verify/DOC-EVID-008...")
    r = requests.post(f"{API_BASE}/verify/DOC-EVID-008", json={
        "decision": "VERIFY",
        "auditor_notes": "SCADA security scope manually inspected and verified.",
        "auditor_name": "Senior Cybersecurity Auditor"
    })
    assert r.status_code == 200, f"Doc verify failed: {r.status_code}"
    print(f"    [PASS] Doc verified: status={r.json()['document']['status']}")

    # 10. Audit Trail
    print("\n[10] Checking GET /api/v1/evidence/audit-trail...")
    r = requests.get(f"{API_BASE}/audit-trail")
    assert r.status_code == 200, f"Audit trail failed: {r.status_code}"
    audit = r.json()
    print(f"    [PASS] Audit Trail: {audit['total_events']} events loaded, total KPI: {audit['kpis']['total_audit_events']}")

    # 11. Frontend Routes HTTP 200 Verification
    print("\n[11] Verifying Next.js Frontend Routes on http://localhost:3000...")
    routes = [
        "/evidence",
        "/evidence/vault",
        "/evidence/verification-queue",
        "/evidence/queue",
        "/evidence/conflicts",
        "/evidence/integrity",
        "/evidence/audit"
    ]

    for route in routes:
        url = f"{FRONTEND_BASE}{route}"
        try:
            fr = requests.get(url, timeout=45)
            assert fr.status_code == 200, f"Route {route} returned status {fr.status_code}"
            print(f"    [PASS] HTTP 200 OK -> {route}")
        except Exception as e:
            print(f"    [FAIL] Error loading {route}: {e}")
            raise

    print("\n==================================================")
    print("ALL 11 BACKEND & FRONTEND VERIFICATION TESTS PASSED!")
    print("==================================================")

if __name__ == "__main__":
    test_evidence_verification_and_conflicts()
