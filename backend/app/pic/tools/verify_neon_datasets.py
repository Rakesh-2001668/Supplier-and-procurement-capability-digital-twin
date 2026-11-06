"""Audit and verify all migrated enterprise datasets in Neon database."""
import json
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parents[3]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import func, select

from app.pic.config import get_settings
from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    Contract, DatasetLoad, FxRate, Invoice, Material, Plant, PurchaseOrder, RuleSet, SpendLine, Supplier, Tenant,
)


def verify() -> dict:
    report = {}

    with system_tx() as s:
        tenants = s.execute(select(Tenant.code, Tenant.name, Tenant.id).order_by(Tenant.code)).all()
        report["databaseHost"] = get_settings().database_url.split("@")[-1].split("/")[0]
        report["tenants"] = [{"code": code, "name": name} for code, name, _ in tenants]

    # 1. Verify D10 & D12: Tenant KAC (Kaveri Auto Components)
    kac = next((t for t in tenants if t[0] == "KAC"), None)
    if kac:
        with tenant_tx(kac[2]) as s:
            vendors = s.execute(select(func.count()).select_from(Supplier)).scalar()
            materials = s.execute(select(func.count()).select_from(Material)).scalar()
            pos = s.execute(select(func.count()).select_from(PurchaseOrder)).scalar()
            invoices = s.execute(select(func.count()).select_from(Invoice)).scalar()
            contracts = s.execute(select(func.count()).select_from(Contract)).scalar()
            spend = s.execute(select(func.count()).select_from(SpendLine)).scalar()
            report["D10_D12_KAC"] = {
                "tenantCode": "KAC",
                "tenantName": kac[1],
                "suppliers": vendors,
                "materials": materials,
                "purchaseOrders": pos,
                "invoices": invoices,
                "contracts": contracts,
                "spendCubeLines": spend,
            }

    # 2. Verify D11: Reference Data & TDS Schedules
    tds_summary = {}
    total_fx = 0
    total_holidays_2027 = 0
    dataset_loads = {}

    for code, _, tid in tenants:
        with tenant_tx(tid) as s:
            # Check TDS rule set
            tds = s.execute(select(RuleSet).where(RuleSet.key == "TDS-SCHEDULE")).scalars().first()
            if tds:
                sections = list(tds.body.get("sections", {}).keys()) if tds.body else []
                tds_summary[code] = {
                    "version": tds.version,
                    "sectionsCount": len(sections),
                    "sections": sections,
                }

            # Check FX rates
            fx_cnt = s.execute(select(func.count()).select_from(FxRate)).scalar()
            total_fx = max(total_fx, fx_cnt)

            # Check 2027 holidays
            for plant in s.execute(select(Plant)).scalars().all():
                if plant.holidays:
                    h2027 = [h for h in plant.holidays if str(h).startswith("2027")]
                    total_holidays_2027 += len(h2027)

            # Check DatasetLoads
            loads = s.execute(select(DatasetLoad.key, DatasetLoad.version, DatasetLoad.loaded_at)).all()
            dataset_loads[code] = {k: v for k, v, _ in loads}

    report["D11_ReferenceData"] = {
        "tdsScheduleLoadedInTenants": list(tds_summary.keys()),
        "sampleTdsSections": tds_summary.get("AXN", {}).get("sections", []),
        "maxFxRatesPerTenant": total_fx,
        "totalPlantHolidays2027": total_holidays_2027,
    }
    report["datasetRegistrySummary"] = dataset_loads

    return report


if __name__ == "__main__":
    rep = verify()
    print("--- NEON DATABASE VERIFICATION REPORT ---")
    print(json.dumps(rep, indent=2, default=str))

