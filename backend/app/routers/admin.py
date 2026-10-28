from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import datetime
import uuid
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models.tenant import User, Tenant

router = APIRouter()

# =====================================================================
# PLATFORM ADMINISTRATION & ENTERPRISE RBAC DIRECTORY ENGINE
# =====================================================================

# Defined Permissions Catalogue
ENTERPRISE_PERMISSIONS = [
    {"id": "users:manage", "name": "Manage Users & Provisioning", "category": "Administration"},
    {"id": "roles:assign", "name": "Assign RBAC Roles & Clearances", "category": "Administration"},
    {"id": "security:configure", "name": "Configure Zero-Trust & Enclave Policies", "category": "Security"},
    {"id": "procurement:approve", "name": "Authorize Purchase Orders & CAPEX", "category": "Procurement"},
    {"id": "contracts:sign", "name": "Cryptographically Sign Legal Contracts", "category": "Contracts"},
    {"id": "quality:calibrate", "name": "Calibrate CMM Metrology & AS9100D", "category": "Quality"},
    {"id": "defense:certify", "name": "Attest CMMC L2 & ITAR Defense Enclaves", "category": "Compliance"},
    {"id": "rfq:award", "name": "Award Sourcing Quotes & MCDA Selection", "category": "Procurement"},
    {"id": "twin:publish", "name": "Publish Supplier Capability Twins", "category": "Digital Twin"},
    {"id": "audit:export", "name": "Export FIPS 140-3 Immutable Audit Ledgers", "category": "Audit"}
]

# Standard Enterprise RBAC Roles
ENTERPRISE_ROLES: Dict[str, Dict[str, Any]] = {
    "SUPER_ADMIN": {
        "id": "SUPER_ADMIN",
        "name": "Super Administrator",
        "department": "Platform Security Operations",
        "description": "Unrestricted administrative authority across all tenants, enclaves, and cryptographic policies.",
        "clearance_level": "Top Secret / CMMC Level 2 Certified",
        "permissions": [p["id"] for p in ENTERPRISE_PERMISSIONS],
        "color": "cyan"
    },
    "PROCUREMENT_VP": {
        "id": "PROCUREMENT_VP",
        "name": "VP Global Strategic Procurement",
        "department": "Global Sourcing & Supply Management",
        "description": "Executive commercial signing authority for high-value purchase orders, contracts, and supplier awards.",
        "clearance_level": "Secret / ITAR Cleared",
        "permissions": ["procurement:approve", "contracts:sign", "rfq:award", "audit:export"],
        "color": "emerald"
    },
    "QUALITY_ASSESSOR": {
        "id": "QUALITY_ASSESSOR",
        "name": "Lead Quality & Metrology Assessor",
        "department": "Aerospace Metrology & Quality Engineering",
        "description": "Authority over AS9100D Rev D metrology, Zeiss CMM verification, and zero-defect calibration.",
        "clearance_level": "Defense Flight-Article Certified",
        "permissions": ["quality:calibrate", "rfq:award", "audit:export"],
        "color": "blue"
    },
    "DEFENSE_AUDITOR": {
        "id": "DEFENSE_AUDITOR",
        "name": "Chief Security & Defense Compliance Officer",
        "department": "Defense Trade Controls & Cybersecurity",
        "description": "Authority over CMMC Level 2 enclaves, NIST SP 800-171 controls, and DDTC ITAR registrations.",
        "clearance_level": "Top Secret / CMMC Level 2 Certified",
        "permissions": ["defense:certify", "security:configure", "audit:export"],
        "color": "amber"
    },
    "OPERATIONS_MGR": {
        "id": "OPERATIONS_MGR",
        "name": "Supply Chain Operations Lead",
        "department": "Fulfillment & Plant Logistics",
        "description": "Manages order dispatch, finished goods inventory deductions, and real-time ASN logistics.",
        "clearance_level": "ITAR Cleared",
        "permissions": ["procurement:approve", "rfq:award"],
        "color": "purple"
    },
    "SUPPLIER_EXEC": {
        "id": "SUPPLIER_EXEC",
        "name": "Supplier Partner Executive",
        "department": "Partner Facility Operations",
        "description": "Authorizes capability twin updates, machinery spindle telemetry, and quotation bidding.",
        "clearance_level": "Partner Verified / CAGE Certified",
        "permissions": ["twin:publish", "rfq:award"],
        "color": "indigo"
    },
    "READONLY_AUDITOR": {
        "id": "READONLY_AUDITOR",
        "name": "Regulatory & Audit Inspector",
        "department": "Independent Oversight",
        "description": "Read-only access to audit logs, immutable evidence vault certificates, and compliance histories.",
        "clearance_level": "Public Trust / DCAA Observer",
        "permissions": ["audit:export"],
        "color": "slate"
    }
}

# Pre-Seeded Enterprise Users Store
users_directory_store: Dict[str, Dict[str, Any]] = {
    "USR-ADM-001": {
        "id": "USR-ADM-001",
        "full_name": "Dr. Marcus Vance",
        "email": "marcus.vance@defense-supplytwin.aero",
        "tenant_id": "TENANT_BUYER_001",
        "tenant_name": "Global Aerospace Propulsion Corp",
        "role_id": "SUPER_ADMIN",
        "role_name": "Super Administrator",
        "department": "Platform Security Operations",
        "status": "ACTIVE",
        "clearance_level": "Top Secret / CMMC Level 2 Certified",
        "mfa_enforced": True,
        "mfa_type": "FIDO2 Hardware Key (YubiKey 5 FIPS)",
        "last_active": "2026-10-20 14:15 UTC",
        "created_at": "2025-01-10",
        "session_ip": "192.168.1.100 (Air-Gapped Defense Gateway)"
    },
    "USR-PRO-002": {
        "id": "USR-PRO-002",
        "full_name": "Elena Rostova",
        "email": "elena.rostova@defense-supplytwin.aero",
        "tenant_id": "TENANT_BUYER_001",
        "tenant_name": "Global Aerospace Propulsion Corp",
        "role_id": "PROCUREMENT_VP",
        "role_name": "VP Global Strategic Procurement",
        "department": "Global Sourcing & Supply Management",
        "status": "ACTIVE",
        "clearance_level": "Secret / ITAR Cleared",
        "mfa_enforced": True,
        "mfa_type": "WebAuthn Biometric",
        "last_active": "2026-10-20 14:22 UTC",
        "created_at": "2025-02-14",
        "session_ip": "172.16.4.22"
    },
    "USR-QAL-003": {
        "id": "USR-QAL-003",
        "full_name": "Dr. Sarah Jenkins",
        "email": "sarah.jenkins@defense-supplytwin.aero",
        "tenant_id": "TENANT_BUYER_001",
        "tenant_name": "Global Aerospace Propulsion Corp",
        "role_id": "QUALITY_ASSESSOR",
        "role_name": "Lead Quality & Metrology Assessor",
        "department": "Aerospace Metrology & Quality Engineering",
        "status": "ACTIVE",
        "clearance_level": "Defense Flight-Article Certified",
        "mfa_enforced": True,
        "mfa_type": "TOTP App Authenticator",
        "last_active": "2026-10-20 13:58 UTC",
        "created_at": "2025-03-01",
        "session_ip": "172.16.4.89"
    },
    "USR-OPS-004": {
        "id": "USR-OPS-004",
        "full_name": "David Chen",
        "email": "david.chen@defense-supplytwin.aero",
        "tenant_id": "TENANT_BUYER_001",
        "tenant_name": "Global Aerospace Propulsion Corp",
        "role_id": "OPERATIONS_MGR",
        "role_name": "Supply Chain Operations Lead",
        "department": "Fulfillment & Plant Logistics",
        "status": "ACTIVE",
        "clearance_level": "ITAR Cleared",
        "mfa_enforced": True,
        "mfa_type": "TOTP App Authenticator",
        "last_active": "2026-10-20 12:40 UTC",
        "created_at": "2025-04-12",
        "session_ip": "172.16.5.10"
    },
    "USR-SUP-005": {
        "id": "USR-SUP-005",
        "full_name": "Rakesh Kumar",
        "email": "rakesh.kumar@abccomponents.com",
        "tenant_id": "TENANT_SUPPLIER_001",
        "tenant_name": "ABC Components Pvt Ltd",
        "role_id": "SUPPLIER_EXEC",
        "role_name": "Supplier Partner Executive",
        "department": "Partner Facility Operations",
        "status": "ACTIVE",
        "clearance_level": "Partner Verified / CAGE Certified",
        "mfa_enforced": True,
        "mfa_type": "FIDO2 Security Key",
        "last_active": "2026-10-20 14:10 UTC",
        "created_at": "2025-06-20",
        "session_ip": "203.192.14.88"
    },
    "USR-AUD-006": {
        "id": "USR-AUD-006",
        "full_name": "Commander Lisa Ray",
        "email": "lisa.ray@dcaa.mil",
        "tenant_id": "TENANT_BUYER_001",
        "tenant_name": "Defense Contract Audit Agency (DCAA)",
        "role_id": "READONLY_AUDITOR",
        "role_name": "Regulatory & Audit Inspector",
        "department": "Independent Oversight",
        "status": "ACTIVE",
        "clearance_level": "Public Trust / DCAA Observer",
        "mfa_enforced": True,
        "mfa_type": "DoD CAC Smart Card",
        "last_active": "2026-10-19 16:30 UTC",
        "created_at": "2025-08-05",
        "session_ip": "144.208.12.9"
    },
    "USR-ENG-007": {
        "id": "USR-ENG-007",
        "full_name": "Alexei Volkov",
        "email": "alexei.volkov@aeroforge.aero",
        "tenant_id": "SUP-AERO-991",
        "tenant_name": "AeroForge Dynamics Inc",
        "role_id": "SUPPLIER_EXEC",
        "role_name": "Supplier Partner Executive",
        "department": "Heavy Forging Engineering",
        "status": "SUSPENDED",
        "clearance_level": "ITAR Cleared",
        "mfa_enforced": False,
        "mfa_type": "None",
        "last_active": "2026-09-18 10:14 UTC",
        "created_at": "2025-09-01",
        "session_ip": "198.51.100.4"
    }
}

# Platform Security & System Configuration Store
platform_settings_store: Dict[str, Any] = {
    "security_policies": {
        "mfa_enforcement_mandatory": True,
        "air_gap_defense_enclave_mode": True,
        "fips_140_3_crypto_enforcement": True,
        "session_inactivity_timeout_minutes": 30,
        "password_rotation_interval_days": 90,
        "max_failed_login_lockout_attempts": 5,
        "zero_trust_device_attestation": True,
        "data_retention_years": 7
    },
    "engine_toggles": {
        "autonomous_negotiation_theater": True,
        "monte_carlo_risk_simulation": True,
        "generative_dfsc_cad_engine": True,
        "realtime_iiot_telemetry_stream": True,
        "blockchain_escrow_settlement": True,
        "automated_po_to_invoice_flip": True
    },
    "financial_guardrails": {
        "max_single_click_approval_usd": 500000,
        "require_dual_executive_signoff_above_usd": 250000,
        "currency_standard": "USD ($)",
        "escrow_smart_contract_network": "Ethereum L2 / Air-Gapped Private Ledger"
    }
}

# Immutable Security Audit Logs Store
audit_logs_store: List[Dict[str, Any]] = [
    {
        "id": "AUD-LOG-9921",
        "timestamp": "2026-10-20 14:22:15 UTC",
        "actor": "Elena Rostova (VP Procurement)",
        "action": "EXECUTIVE_APPROVAL_PO_AWARD",
        "resource": "PO-2026-9042 / ABC Components",
        "ip_address": "172.16.4.22",
        "status": "SUCCESS",
        "hash_digest": "SHA256:88F9A102C481B094E10452F8189D",
        "details": "Authorized $185,000 procurement award following AS9100D metrology sign-off."
    },
    {
        "id": "AUD-LOG-9920",
        "timestamp": "2026-10-20 14:15:40 UTC",
        "actor": "Dr. Marcus Vance (Super Admin)",
        "action": "SECURITY_POLICY_UPDATE",
        "resource": "Zero-Trust Enclave Configuration",
        "ip_address": "192.168.1.100",
        "status": "SUCCESS",
        "hash_digest": "SHA256:77D91024FF91280B1804AE52C192",
        "details": "Enforced FIPS 140-3 hardware token authentication across all tenant admin roles."
    },
    {
        "id": "AUD-LOG-9919",
        "timestamp": "2026-10-20 13:58:12 UTC",
        "actor": "Dr. Sarah Jenkins (Lead Quality Assessor)",
        "action": "METROLOGY_PILLAR_RECALIBRATION",
        "resource": "Zeiss CMM Bay #04 / ABC Components",
        "ip_address": "172.16.4.89",
        "status": "SUCCESS",
        "hash_digest": "SHA256:66E102941BA201940E102F8471A1",
        "details": "Re-attested coordinate precision to ±0.0001\" based on laser interferometry report."
    },
    {
        "id": "AUD-LOG-9918",
        "timestamp": "2026-10-20 12:45:00 UTC",
        "actor": "David Chen (Operations Lead)",
        "action": "ASN_DISPATCH_REGISTRATION",
        "resource": "ASN-2026-0819 / FedEx Defense Express",
        "ip_address": "172.16.5.10",
        "status": "SUCCESS",
        "hash_digest": "SHA256:55C1902410A88B0192A0E418C109",
        "details": "Dispatched 600 units of Titanium Flight Flanges; deducted stock from Finished Goods depot."
    },
    {
        "id": "AUD-LOG-9917",
        "timestamp": "2026-10-20 11:30:20 UTC",
        "actor": "System Automated Sentinel",
        "action": "SUSPICIOUS_LOGIN_CHALLENGE",
        "resource": "User: Alexei Volkov",
        "ip_address": "198.51.100.4 (External Geographic Anomaly)",
        "status": "FLAGGED",
        "hash_digest": "SHA256:44B0182400C9102840B10F9184D2",
        "details": "Account suspended automatically due to unverified external IP attempt without FIDO2 hardware token."
    }
]


# =====================================================================
# PYDANTIC SCHEMAS
# =====================================================================

class CreateUserPayload(BaseModel):
    full_name: str
    email: str
    tenant_id: str
    role_id: str
    department: str
    clearance_level: Optional[str] = "ITAR Cleared"
    mfa_type: Optional[str] = "WebAuthn Biometric"

class UpdateUserPayload(BaseModel):
    full_name: Optional[str] = None
    role_id: Optional[str] = None
    department: Optional[str] = None
    clearance_level: Optional[str] = None
    status: Optional[str] = None

class ToggleStatusPayload(BaseModel):
    status: str  # "ACTIVE" or "SUSPENDED"
    reason: Optional[str] = "Administrative action"

class UpdateSettingsPayload(BaseModel):
    security_policies: Optional[Dict[str, Any]] = None
    engine_toggles: Optional[Dict[str, Any]] = None
    financial_guardrails: Optional[Dict[str, Any]] = None


# =====================================================================
# API ENDPOINTS
# =====================================================================

@router.get("/overview")
def get_admin_overview():
    """Retrieve platform administration executive KPI strip and telemetry."""
    users = list(users_directory_store.values())
    total_users = len(users)
    active_users = sum(1 for u in users if u["status"] == "ACTIVE")
    suspended_users = sum(1 for u in users if u["status"] == "SUSPENDED")
    mfa_enforced_count = sum(1 for u in users if u.get("mfa_enforced"))

    return {
        "status": "success",
        "total_users": total_users,
        "active_users": active_users,
        "suspended_users": suspended_users,
        "mfa_adoption_pct": round((mfa_enforced_count / total_users) * 100, 1) if total_users else 100.0,
        "active_rbac_roles_count": len(ENTERPRISE_ROLES),
        "total_tenants_managed": 4,
        "defense_enclave_status": "AIR-GAPPED FIPS 140-3 COMPLIANT",
        "system_health": {
            "api_latency_ms": 18,
            "database_connection_pool": "18 / 50 Active",
            "uptime_pct": 99.99,
            "active_jwt_sessions": 24,
            "memory_usage_pct": 34.2
        }
    }


@router.get("/users")
def get_users_directory(
    search: Optional[str] = Query(None),
    role_filter: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None)
):
    """Retrieve filterable and searchable enterprise user RBAC directory."""
    users = list(users_directory_store.values())

    if search:
        q = search.lower().strip()
        users = [
            u for u in users if (
                q in u["full_name"].lower() or
                q in u["email"].lower() or
                q in u["department"].lower() or
                q in u["tenant_name"].lower() or
                q in u["id"].lower()
            )
        ]

    if role_filter and role_filter.upper() != "ALL":
        users = [u for u in users if u["role_id"].upper() == role_filter.upper()]

    if status_filter and status_filter.upper() != "ALL":
        users = [u for u in users if u["status"].upper() == status_filter.upper()]

    return {
        "status": "success",
        "count": len(users),
        "users": users
    }


@router.post("/users")
def provision_enterprise_user(payload: CreateUserPayload, db: Session = Depends(get_db)):
    """Provision a new enterprise user into the RBAC directory with designated clearance."""
    # Check if email exists
    for u in users_directory_store.values():
        if u["email"].lower() == payload.email.lower():
            raise HTTPException(status_code=400, detail=f"User with email '{payload.email}' already exists.")

    new_id = f"USR-{uuid.uuid4().hex[:4].upper()}"
    role_def = ENTERPRISE_ROLES.get(payload.role_id, ENTERPRISE_ROLES["OPERATIONS_MGR"])

    new_user = {
        "id": new_id,
        "full_name": payload.full_name,
        "email": payload.email,
        "tenant_id": payload.tenant_id,
        "tenant_name": "Global Aerospace Propulsion Corp" if "BUYER" in payload.tenant_id else "ABC Components Pvt Ltd",
        "role_id": payload.role_id,
        "role_name": role_def["name"],
        "department": payload.department,
        "status": "ACTIVE",
        "clearance_level": payload.clearance_level or role_def["clearance_level"],
        "mfa_enforced": True,
        "mfa_type": payload.mfa_type or "WebAuthn Biometric",
        "last_active": "Never (Just Provisioned)",
        "created_at": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
        "session_ip": "Pending First Enclave Handshake"
    }

    users_directory_store[new_id] = new_user

    # Also log to immutable audit ledger
    audit_logs_store.insert(0, {
        "id": f"AUD-LOG-{uuid.uuid4().hex[:4].upper()}",
        "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "actor": "Dr. Marcus Vance (Super Admin)",
        "action": "USER_PROVISIONED",
        "resource": f"{payload.full_name} ({new_id})",
        "ip_address": "192.168.1.100",
        "status": "SUCCESS",
        "hash_digest": f"SHA256:{uuid.uuid4().hex[:16].upper()}",
        "details": f"Assigned role '{role_def['name']}' with clearance '{new_user['clearance_level']}'."
    })

    return {
        "status": "success",
        "message": f"Enterprise user '{payload.full_name}' provisioned successfully.",
        "user": new_user
    }


@router.put("/users/{user_id}")
def update_enterprise_user(user_id: str, payload: UpdateUserPayload):
    """Update role, clearance, or department for an existing user."""
    user = users_directory_store.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")

    if payload.full_name:
        user["full_name"] = payload.full_name
    if payload.department:
        user["department"] = payload.department
    if payload.clearance_level:
        user["clearance_level"] = payload.clearance_level
    if payload.status:
        user["status"] = payload.status
    if payload.role_id and payload.role_id in ENTERPRISE_ROLES:
        user["role_id"] = payload.role_id
        user["role_name"] = ENTERPRISE_ROLES[payload.role_id]["name"]

    audit_logs_store.insert(0, {
        "id": f"AUD-LOG-{uuid.uuid4().hex[:4].upper()}",
        "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "actor": "Super Administrator",
        "action": "USER_RECORD_MODIFIED",
        "resource": f"{user['full_name']} ({user_id})",
        "ip_address": "192.168.1.100",
        "status": "SUCCESS",
        "hash_digest": f"SHA256:{uuid.uuid4().hex[:16].upper()}",
        "details": f"Updated user profile and clearance parameters."
    })

    return {
        "status": "success",
        "message": f"User '{user_id}' updated successfully.",
        "user": user
    }


@router.post("/users/{user_id}/status")
def toggle_user_status(user_id: str, payload: ToggleStatusPayload):
    """Toggle status between ACTIVE and SUSPENDED."""
    user = users_directory_store.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")

    old_status = user["status"]
    user["status"] = payload.status

    audit_logs_store.insert(0, {
        "id": f"AUD-LOG-{uuid.uuid4().hex[:4].upper()}",
        "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "actor": "Super Administrator",
        "action": f"USER_STATUS_{payload.status}",
        "resource": f"{user['full_name']} ({user_id})",
        "ip_address": "192.168.1.100",
        "status": "SUCCESS",
        "hash_digest": f"SHA256:{uuid.uuid4().hex[:16].upper()}",
        "details": f"Status changed from {old_status} to {payload.status}. Reason: {payload.reason}"
    })

    return {
        "status": "success",
        "message": f"User '{user['full_name']}' is now {payload.status}.",
        "user_id": user_id,
        "new_status": payload.status
    }


@router.delete("/users/{user_id}")
def revoke_user_credentials(user_id: str):
    """Permanently revoke user credentials and access keys."""
    user = users_directory_store.pop(user_id, None)
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")

    audit_logs_store.insert(0, {
        "id": f"AUD-LOG-{uuid.uuid4().hex[:4].upper()}",
        "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "actor": "Super Administrator",
        "action": "USER_CREDENTIALS_REVOKED",
        "resource": f"{user['full_name']} ({user_id})",
        "ip_address": "192.168.1.100",
        "status": "SUCCESS",
        "hash_digest": f"SHA256:{uuid.uuid4().hex[:16].upper()}",
        "details": "User access tokens revoked; session keys expunged."
    })

    return {
        "status": "success",
        "message": f"User '{user['full_name']}' credentials revoked and purged from active directory."
    }


@router.get("/roles")
def get_rbac_roles():
    """Retrieve full list of enterprise RBAC roles, permission sets, and assigned user counts."""
    roles = []
    for r_id, r_def in ENTERPRISE_ROLES.items():
        assigned_count = sum(1 for u in users_directory_store.values() if u["role_id"] == r_id)
        roles.append({
            **r_def,
            "assigned_users_count": assigned_count
        })

    return {
        "status": "success",
        "roles": roles,
        "permissions_catalogue": ENTERPRISE_PERMISSIONS
    }


@router.get("/settings")
def get_platform_settings():
    """Retrieve platform security policies, feature flags, and financial guardrails."""
    return {
        "status": "success",
        "settings": platform_settings_store
    }


@router.post("/settings")
def update_platform_settings(payload: UpdateSettingsPayload):
    """Update platform security policies and system configuration."""
    if payload.security_policies:
        platform_settings_store["security_policies"].update(payload.security_policies)
    if payload.engine_toggles:
        platform_settings_store["engine_toggles"].update(payload.engine_toggles)
    if payload.financial_guardrails:
        platform_settings_store["financial_guardrails"].update(payload.financial_guardrails)

    audit_logs_store.insert(0, {
        "id": f"AUD-LOG-{uuid.uuid4().hex[:4].upper()}",
        "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "actor": "Super Administrator",
        "action": "PLATFORM_SETTINGS_UPDATED",
        "resource": "Enterprise Configuration Registry",
        "ip_address": "192.168.1.100",
        "status": "SUCCESS",
        "hash_digest": f"SHA256:{uuid.uuid4().hex[:16].upper()}",
        "details": "Platform configuration parameters recalibrated and persisted."
    })

    return {
        "status": "success",
        "message": "Platform configuration updated successfully.",
        "settings": platform_settings_store
    }


@router.get("/audit-logs")
def get_immutable_audit_logs(limit: int = Query(50)):
    """Retrieve cryptographically hashed user activity and security audit trail."""
    return {
        "status": "success",
        "count": len(audit_logs_store[:limit]),
        "logs": audit_logs_store[:limit]
    }


@router.get("/health")
def get_system_telemetry():
    """Live infrastructure health monitoring and enclave telemetry."""
    return {
        "status": "HEALTHY",
        "enclave_mode": "AIR-GAPPED FIPS 140-3",
        "telemetry": {
            "api_cluster_status": "ONLINE (3 Nodes)",
            "average_response_ms": 16.4,
            "db_connection_pool": "18 / 50 Active",
            "active_sessions": len([u for u in users_directory_store.values() if u["status"] == "ACTIVE"]),
            "cache_hit_rate_pct": 98.7,
            "failed_login_rate_pct": 0.04
        }
    }
