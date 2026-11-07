"""Turnkey Client ERP Onboarding Accelerator Pack Loader (TD §12, Item 50).

Loads, validates, and stores client-specific ERP production field mappings,
taxonomy templates, and organizational crosswalks into the Neon database.

Usage:
    python -m app.pic.tools.onboarding_pack --tenant KAC --apply-mappings
    python -m app.pic.tools.onboarding_pack --all-tenants --apply-mappings
    python -m app.pic.tools.onboarding_pack --tenant KAC --dry-run
"""
import argparse
import json
import logging
import sys
import uuid
from pathlib import Path

# Ensure backend root is on sys.path
_BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from typing import Optional

from sqlalchemy import func, select

from app.pic.config import BACKEND_DIR
from app.pic.db import engine, system_tx, tenant_tx
from app.pic.models import AppUser, IntegrationFieldMapping, Tenant
from app.pic.platform import audit, clock, field_mapping

log = logging.getLogger("pic.onboarding_pack")

ONBOARDING_KIT_DIR = BACKEND_DIR / "data" / "onboarding_kit"
RULES_DIR = ONBOARDING_KIT_DIR / "rules"
TEMPLATES_DIR = ONBOARDING_KIT_DIR / "templates"

# Rule files to load: (target_system, message_type, rule_file_name, note)
DEFAULT_MAPPINGS = [
    ("SAP_S4", "PURCHASE_ORDER", "SAP_S4_PURCHASE_ORDER.json", "Turnkey Onboarding: SAP S/4HANA PO BAPI mapping"),
    ("SAP_S4", "SUPPLIER_INVOICE", "SAP_S4_SUPPLIER_INVOICE.json", "Turnkey Onboarding: SAP S/4HANA Invoice verification mapping"),
    ("SAP_S4", "GOODS_RECEIPT", "SAP_S4_GOODS_RECEIPT.json", "Turnkey Onboarding: SAP S/4HANA Material document GR mapping"),
    ("SAP_S4", "PAYMENT", "SAP_S4_PAYMENT.json", "Turnkey Onboarding: SAP S/4HANA Payment clearing mapping"),
    ("ORACLE_FUSION", "PURCHASE_ORDER", "ORACLE_FUSION_PURCHASE_ORDER.json", "Turnkey Onboarding: Oracle Fusion Cloud PO mapping"),
]


def load_rules_from_file(filename: str) -> list[dict]:
    path = RULES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Rules file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Rules in {filename} must be a JSON array")
    return data


def validate_pack() -> list[dict]:
    """Validate all rule sets in the onboarding pack against field_mapping engine."""
    results = []
    for target_system, message_type, filename, note in DEFAULT_MAPPINGS:
        rules = load_rules_from_file(filename)
        problems = field_mapping.validate(rules)
        results.append({
            "target_system": target_system,
            "message_type": message_type,
            "file": filename,
            "rules_count": len(rules),
            "valid": len(problems) == 0,
            "problems": problems,
        })
    return results


def apply_mappings_for_tenant(
    tenant_code: str,
    dry_run: bool = False,
    user_id: Optional[uuid.UUID] = None,
) -> dict:
    """Store and activate all baseline ERP production field mappings in Neon DB for a tenant."""
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == tenant_code)).scalar_one_or_none()
        if not tenant:
            raise ValueError(f"Tenant {tenant_code!r} does not exist in database")
        tenant_id = tenant.id

    report = {"tenant": tenant_code, "dry_run": dry_run, "mappings": []}

    with tenant_tx(tenant_id) as s:
        # Determine actor for audit
        actor_id = user_id
        if not actor_id:
            admin_user = s.execute(
                select(AppUser).where(AppUser.roles.contains(["TENANT_ADMIN"])).limit(1)
            ).scalar_one_or_none()
            actor_id = admin_user.id if admin_user else None

        for target_system, message_type, filename, note in DEFAULT_MAPPINGS:
            rules = load_rules_from_file(filename)
            problems = field_mapping.validate(rules)
            if problems:
                raise ValueError(f"Invalid rules in {filename}: {problems}")

            # Check existing active mapping
            existing_active = s.execute(
                select(IntegrationFieldMapping).where(
                    IntegrationFieldMapping.target_system == target_system,
                    IntegrationFieldMapping.message_type == message_type,
                    IntegrationFieldMapping.status == "ACTIVE",
                )
            ).scalar_one_or_none()

            if existing_active:
                if existing_active.rules == rules:
                    report["mappings"].append({
                        "target_system": target_system,
                        "message_type": message_type,
                        "version": existing_active.version,
                        "status": "ALREADY_ACTIVE",
                        "rules_count": len(rules),
                    })
                    continue

                if not dry_run:
                    # Retire existing version
                    existing_active.status = "RETIRED"
                    s.flush()

            if dry_run:
                report["mappings"].append({
                    "target_system": target_system,
                    "message_type": message_type,
                    "version": (existing_active.version + 1) if existing_active else 1,
                    "status": "DRY_RUN_VALID",
                    "rules_count": len(rules),
                })
                continue

            # Calculate next version
            next_version = int(
                s.execute(
                    select(func.max(IntegrationFieldMapping.version)).where(
                        IntegrationFieldMapping.target_system == target_system,
                        IntegrationFieldMapping.message_type == message_type,
                    )
                ).scalar()
                or 0
            ) + 1

            new_mapping = IntegrationFieldMapping(
                tenant_id=tenant_id,
                target_system=target_system,
                message_type=message_type,
                version=next_version,
                status="ACTIVE",
                rules=rules,
                note=note,
                published_at=clock.now(),
                published_by=actor_id,
                created_by=actor_id,
            )
            s.add(new_mapping)
            s.flush()

            audit.record(
                s,
                "FIELD_MAPPING",
                new_mapping.id,
                "ONBOARDING_ACTIVATED",
                object_ref=f"{target_system}/{message_type}@v{next_version}",
                actor="onboarding_accelerator",
                after={"rules": len(rules), "note": note},
            )

            report["mappings"].append({
                "target_system": target_system,
                "message_type": message_type,
                "version": next_version,
                "status": "ACTIVATED",
                "rules_count": len(rules),
            })

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Turnkey Client ERP Onboarding Pack Loader")
    parser.add_argument("--tenant", help="Target tenant code (e.g. KAC, AXN)")
    parser.add_argument("--all-tenants", action="store_true", help="Apply to all active tenants in DB")
    parser.add_argument("--apply-mappings", action="store_true", help="Store and activate mappings in DB")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing to DB")
    parser.add_argument("--validate-only", action="store_true", help="Validate pack files syntax only")
    args = parser.parse_args()

    # UTF-8 stdout
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 80)
    print("TURNKEY CLIENT ERP ONBOARDING ACCELERATOR PACK")
    print("=" * 80)

    # 1. Validate files
    validation = validate_pack()
    print("\n1. VALIDATING ONBOARDING RULE FILES:")
    all_valid = True
    for item in validation:
        status_str = "OK" if item["valid"] else "FAILED"
        print(f"   [{status_str:<6}] {item['target_system']:<15} {item['message_type']:<22} ({item['rules_count']} rules) -> {item['file']}")
        if not item["valid"]:
            all_valid = False
            for p in item["problems"]:
                print(f"          Problem: {p}")

    if not all_valid:
        print("\nValidation failed: Fix rule syntax problems before applying.")
        return 1

    if args.validate_only:
        print("\nAll rule files validated successfully.")
        return 0

    # 2. Determine target tenants
    with system_tx() as s:
        tenants = s.execute(select(Tenant.code, Tenant.name).order_by(Tenant.code)).fetchall()

    if args.all_tenants:
        target_codes = [t.code for t in tenants]
    elif args.tenant:
        target_codes = [args.tenant.upper()]
    else:
        print("\nSpecify either --tenant <CODE> or --all-tenants (or --validate-only).")
        print(f"Available tenants in database: {', '.join(t.code for t in tenants)}")
        return 0

    # 3. Apply or Dry-Run
    dry_run = args.dry_run or not args.apply_mappings
    mode_str = "DRY RUN (no database writes)" if dry_run else "LIVE APPLICATION TO NEON DATABASE"
    print(f"\n2. EXECUTING IN MODE: {mode_str}")

    for code in target_codes:
        print(f"\n--- Processing Tenant: [{code}] ---")
        try:
            res = apply_mappings_for_tenant(code, dry_run=dry_run)
            for m in res["mappings"]:
                print(f"   * {m['target_system']:<15} {m['message_type']:<22} v{m['version']} -> {m['status']} ({m['rules_count']} rules)")
        except Exception as e:
            print(f"   [ERROR] Failed for tenant {code}: {e}")

    print("\n" + "=" * 80)
    print("COMPLETED.")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
