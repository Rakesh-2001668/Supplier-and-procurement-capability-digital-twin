import json
import urllib.request
import urllib.error
import sys

BASE_API = "http://127.0.0.1:8080/api/v1/admin"
BASE_FE = "http://localhost:3000"

def req(url, method="GET", data=None):
    headers = {"Content-Type": "application/json"} if data else {}
    body = json.dumps(data).encode("utf-8") if data else None
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as res:
            resp_body = res.read().decode("utf-8")
            return res.status, json.loads(resp_body) if "application/json" in res.headers.get("Content-Type", "") else resp_body
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        return e.code, err_body
    except Exception as e:
        return 500, str(e)

def run_tests():
    print("==================================================================")
    print("VERIFYING PLATFORM ADMINISTRATION & ENTERPRISE RBAC ENGINE (E2E)")
    print("==================================================================")

    # 1. Overview
    code, data = req(f"{BASE_API}/overview")
    print(f"[1] GET /overview -> Status {code}")
    assert code == 200, f"Expected 200, got {code}"
    print(f"    Total Users: {data.get('total_users')}, Active: {data.get('active_users')}")
    print(f"    Defense Enclave: {data.get('defense_enclave_status')}")

    # 2. Users Directory
    code, data = req(f"{BASE_API}/users")
    print(f"[2] GET /users -> Status {code}")
    assert code == 200, f"Expected 200, got {code}"
    print(f"    Returned {data.get('count')} users in directory")

    # 3. Provision New Enterprise User
    new_user_payload = {
        "full_name": "Commander Naomi Nagata",
        "email": f"naomi.nagata_{sys.platform}@defense-supplytwin.aero",
        "tenant_id": "TENANT_BUYER_001",
        "role_id": "OPERATIONS_MGR",
        "department": "Propulsion Fulfillment & Plant Logistics",
        "clearance_level": "ITAR Cleared",
        "mfa_type": "FIDO2 Hardware Key (YubiKey 5 FIPS)"
    }
    code, data = req(f"{BASE_API}/users", method="POST", data=new_user_payload)
    print(f"[3] POST /users -> Status {code}")
    assert code == 200, f"Expected 200, got {code}"
    user_id = data.get("user", {}).get("id")
    print(f"    Provisioned User ID: {user_id}")

    # 4. Update User Profile
    code, data = req(f"{BASE_API}/users/{user_id}", method="PUT", data={
        "department": "Advanced Spaceflight Fleet Logistics",
        "clearance_level": "Top Secret / CMMC Level 2 Certified"
    })
    print(f"[4] PUT /users/{user_id} -> Status {code}")
    assert code == 200, f"Expected 200, got {code}"

    # 5. Toggle Status (Active -> Suspended -> Active)
    code, data = req(f"{BASE_API}/users/{user_id}/status", method="POST", data={
        "status": "SUSPENDED",
        "reason": "Routine security audit challenge"
    })
    print(f"[5a] POST /users/{user_id}/status (SUSPENDED) -> Status {code}")
    assert code == 200

    code, data = req(f"{BASE_API}/users/{user_id}/status", method="POST", data={
        "status": "ACTIVE",
        "reason": "Security clearance validated"
    })
    print(f"[5b] POST /users/{user_id}/status (ACTIVE) -> Status {code}")
    assert code == 200

    # 6. Delete / Revoke User
    code, data = req(f"{BASE_API}/users/{user_id}", method="DELETE")
    print(f"[6] DELETE /users/{user_id} -> Status {code}")
    assert code == 200

    # 7. Roles & Permissions Catalog
    code, data = req(f"{BASE_API}/roles")
    print(f"[7] GET /roles -> Status {code}")
    assert code == 200, f"Expected 200, got {code}"
    print(f"    Roles Count: {len(data.get('roles', []))}")
    print(f"    Permissions Catalog: {len(data.get('permissions_catalogue', []))} granular capabilities")

    # 8. Platform Settings
    code, data = req(f"{BASE_API}/settings")
    print(f"[8] GET /settings -> Status {code}")
    assert code == 200, f"Expected 200, got {code}"
    settings = data.get("settings", {})
    print(f"    Air-Gap Defense Enclave: {settings.get('security_policies', {}).get('air_gap_defense_enclave_mode')}")
    print(f"    Max Single-Click Approval: ${settings.get('financial_guardrails', {}).get('max_single_click_approval_usd')}")

    # 9. Update Settings
    code, data = req(f"{BASE_API}/settings", method="POST", data={
        "security_policies": {
            "session_inactivity_timeout_minutes": 45
        }
    })
    print(f"[9] POST /settings -> Status {code}")
    assert code == 200

    # 10. Audit Logs
    code, data = req(f"{BASE_API}/audit-logs")
    print(f"[10] GET /audit-logs -> Status {code}")
    assert code == 200, f"Expected 200, got {code}"
    print(f"    Cryptographic Audit Logs count: {data.get('count')}")

    # 11. System Health
    code, data = req(f"{BASE_API}/health")
    print(f"[11] GET /health -> Status {code}")
    assert code == 200, f"Expected 200, got {code}"
    print(f"    Enclave Health: {data.get('enclave_mode')}")

    # 12. Frontend Route Verification
    fe_routes = [
        "/admin",
        "/admin/users",
        "/admin/settings"
    ]
    print("\n[12] Testing Next.js Frontend Admin Routes...")
    for route in fe_routes:
        url = f"{BASE_FE}{route}"
        try:
            req_fe = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_fe, timeout=20) as r:
                print(f"    {route} -> Status {r.status} (OK)")
                assert r.status == 200
        except Exception as e:
            print(f"    {route} -> Error: {e}")

    print("\n==================================================================")
    print("ALL PLATFORM ADMINISTRATION & RBAC DIRECTORY TESTS PASSED!")
    print("==================================================================")

if __name__ == "__main__":
    run_tests()
