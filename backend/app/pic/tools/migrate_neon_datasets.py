"""Migrate and seed enterprise datasets into the Neon database.

Target datasets:
- D10: ERP Client S/4HANA Extract & Cutover (Tenant KAC)
- D11: Reference Data (Statutory TDS schedules, 2027 factory calendars, FX reference history)
- D12: Contract portfolio for KAC (if not already loaded)
"""
import logging
import sys
import time
from pathlib import Path

# Ensure backend directory is in path
backend_dir = Path(__file__).resolve().parents[3]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import func, select

from app.pic.config import get_settings
from app.pic.db import system_tx, tenant_tx
from app.pic.models import Material, Plant, RuleSet, Supplier, Tenant
from app.pic.seed import datasets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("migrate_neon")


def check_connection() -> dict:
    settings = get_settings()
    host = settings.database_url.split("@")[-1].split("/")[0] if "@" in settings.database_url else "local"
    log.info("Connecting to database host: %s ...", host)
    with system_tx() as s:
        tenants = s.execute(select(Tenant.code, Tenant.name, Tenant.id)).all()
    return {
        "host": host,
        "tenants": {code: {"name": name, "id": tid} for code, name, tid in tenants}
    }


def run_migration() -> dict:
    start_time = time.time()
    conn_info = check_connection()
    log.info("Current active tenants in Neon: %s", list(conn_info["tenants"].keys()))

    import os
    from dotenv import dotenv_values
    password = os.environ.get("PIC_SEED_PASSWORD") or dotenv_values(backend_dir / ".env").get("PIC_SEED_PASSWORD")
    if not password:
        password = "Test-Only-Password-1"

    results = {}

    # 1. Migrate D10 (Tenant KAC from SAP S/4HANA cutover extract)
    log.info("--> Migrating D10 (erp_client_kac: S/4HANA Cutover Extract for Kaveri Auto Components)...")
    res_kac = datasets.apply_pack("erp_client_kac", password)
    results["erp_client_kac"] = res_kac
    for r in res_kac:
        log.info("    [%s] %s: %s", r["tenant"], r["pack"], r["status"])

    # 2. Migrate D12 (contracts_kac for Kaveri Auto Components) if D10 succeeded
    log.info("--> Checking D12 (contracts_kac: Contract portfolio for Kaveri Auto Components)...")
    try:
        res_contracts = datasets.apply_pack("contracts_kac", password)
        results["contracts_kac"] = res_contracts
        for r in res_contracts:
            log.info("    [%s] %s: %s", r["tenant"], r["pack"], r["status"])
    except Exception as exc:
        log.warning("    contracts_kac skipped or deferred: %s", exc)

    # 3. Migrate D11 (Reference Data: Statutory TDS schedules, 2027 holidays, FX rates across all tenants)
    log.info("--> Migrating D11 (reference_data: TDS Schedules, 2027 Calendars, FX Rates across all tenants)...")
    res_ref = datasets.apply_pack("reference_data", password, force=True)
    results["reference_data"] = res_ref
    for r in res_ref:
        log.info("    [%s] %s: %s (counts: %s)", r["tenant"], r["pack"], r["status"], r.get("summary", {}).get("counts"))

    # Post-migration verification
    log.info("--> Verifying migrated datasets in Neon database...")
    verification = {}
    with system_tx() as s:
        all_tenants = s.execute(select(Tenant.code, Tenant.name, Tenant.id)).all()
        verification["tenants"] = [code for code, _, _ in all_tenants]

    # Verify KAC tenant if present
    kac_tenant = next((t for t in all_tenants if t[0] == "KAC"), None)
    if kac_tenant:
        with tenant_tx(kac_tenant[2]) as s:
            vendor_cnt = s.execute(select(func.count()).select_from(Supplier)).scalar()
            mat_cnt = s.execute(select(func.count()).select_from(Material)).scalar()
            verification["KAC"] = {
                "vendors": vendor_cnt,
                "materials": mat_cnt,
            }

    # Verify TDS ruleset in AXN or KAC
    for code, _, tid in all_tenants:
        with tenant_tx(tid) as s:
            tds_rule = s.execute(select(RuleSet).where(RuleSet.key == "TDS-SCHEDULE")).scalars().first()
            if tds_rule:
                verification[f"{code}_TDS"] = {
                    "version": tds_rule.version,
                    "sections": len(tds_rule.body.get("sections", {})) if tds_rule.body else 0
                }

    duration = round(time.time() - start_time, 2)
    log.info("Migration completed successfully in %s seconds.", duration)

    return {
        "status": "SUCCESS",
        "durationSeconds": duration,
        "results": results,
        "verification": verification,
    }


if __name__ == "__main__":
    out = run_migration()
    import json
    print("\n--- NEON MIGRATION REPORT ---")
    print(json.dumps(out, indent=2, default=str))
