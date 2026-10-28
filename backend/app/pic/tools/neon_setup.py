"""Load everything into the PostgreSQL database in DATABASE_URL (Neon).

    python -m app.pic.tools.neon_setup                # migrate, seed, transfer legacy data, verify
    python -m app.pic.tools.neon_setup --verify-only

Steps
1. PIC schema: Alembic migrations 0001 (87 tables) and 0002 (pic_app role, row-level security, append-only audit).
2. PIC data: the Axion Mobility signature case run through the services (only if tenant AXN does not exist yet).
3. Legacy data from the snapshot extracted from the Docker supplier_twin database (app.pic.tools.legacy_extract):
   a. the existing app's Alembic chain (public schema) and a verbatim copy of all 15 legacy tables;
   b. the §15 migration into PIC (one tenant per legacy buyer) with live continuation of the open items and a
      reconciliation report written to docs/PIC_Legacy_Migration_Report.md.
   Without a snapshot, capability_twin.db (SQLite) is copied verbatim instead.
4. Verification: row counts, RLS coverage, audit hash chain, pending events.

Safe to re-run: migrations are versioned, seeds skip existing tenants, legacy rows are inserted ON CONFLICT DO NOTHING.
"""
import argparse
import os
import secrets
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import DateTime, MetaData, create_engine, select, text
from sqlalchemy.dialects.postgresql import insert

from app.pic.config import BACKEND_DIR, get_settings
from app.pic.tools import legacy_extract

LEGACY_SQLITE = BACKEND_DIR / "capability_twin.db"
LEGACY_TABLES = legacy_extract.TABLES  # parent tables first so foreign keys resolve
REPORT = BACKEND_DIR.parent / "docs" / "PIC_Legacy_Migration_Report.md"


def _target() -> str:
    url = get_settings().sqlalchemy_url
    host = url.split("@")[-1].split("?")[0]
    return host


def migrate_pic() -> None:
    config = Config(str(BACKEND_DIR / "alembic_pic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "pic_migrations"))
    command.upgrade(config, "head")


def seed_pic(password: str | None) -> list[str] | None:
    import app.pic.services  # noqa: F401
    from app.pic.db import system_tx
    from app.pic.models import Tenant
    from app.pic.seed import axion
    with system_tx() as s:
        tenants = s.execute(select(Tenant.id, Tenant.code)).all()
        present = any(code == axion.TENANT[0] for _, code in tenants)
    if present:
        from app.pic.seed import reference
        reference.deploy_process_definitions()
        for tenant_id, code in tenants:
            added = reference.ensure_extensions(tenant_id)
            print(f"  tenant {code} already present – seed skipped; upgraded: {', '.join(added) if added else 'nothing to add'}")
        return None
    return axion.run(password)


def migrate_legacy() -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")


def legacy_rows(snapshot_path: Path) -> tuple[dict, str]:
    """Rows per legacy table: the extracted Docker snapshot, or capability_twin.db when there is none."""
    if snapshot_path.exists():
        snapshot = legacy_extract.load(snapshot_path)
        return snapshot["tables"], f"snapshot {snapshot_path.name} ({snapshot['source'].get('kind')}, extracted {snapshot['extractedAt']})"
    if LEGACY_SQLITE.exists():
        tables, _, _ = legacy_extract.from_sqlite(LEGACY_SQLITE)
        return tables, LEGACY_SQLITE.name
    return {}, "none"


def copy_legacy(tables: dict) -> dict:
    """Verbatim copy into the legacy public schema (all columns, legacy ids kept)."""
    engine = create_engine(get_settings().sqlalchemy_url)
    meta = MetaData(schema="public")
    meta.reflect(bind=engine, only=[t for t in LEGACY_TABLES if t in tables])
    copied = {}
    with engine.begin() as conn:
        for name in LEGACY_TABLES:
            table = meta.tables.get(f"public.{name}")
            if table is None or name not in tables:
                continue
            columns = {c.name: c for c in table.columns}
            missing = sorted({k for r in tables[name] for k in r} - set(columns))
            if missing:
                raise RuntimeError(f"public.{name} lacks columns {missing}; run the legacy migrations first")
            rows = [{k: (datetime.fromisoformat(v) if v and isinstance(columns[k].type, DateTime) else v) for k, v in r.items()}
                    for r in tables[name]]
            if rows:
                keys = [c.name for c in table.primary_key.columns] or ["id"]
                result = conn.execute(insert(table).values(rows).on_conflict_do_nothing(index_elements=keys))
                copied[name] = (len(rows), result.rowcount)
            else:
                copied[name] = (0, 0)
    return copied


def migrate_legacy_into_pic(snapshot_path: Path, password: str, fx: Decimal) -> list[dict]:
    import app.pic.services  # noqa: F401
    from app.pic.seed import legacy
    from app.pic.tools import migration_report
    snapshot = legacy_extract.load(snapshot_path)
    reports = legacy.migrate(snapshot, password, fx)
    if any("skipped" not in r for r in reports):
        REPORT.write_text(migration_report.render(snapshot, reports), encoding="utf-8")
    return reports


def verify() -> dict:
    engine = create_engine(get_settings().sqlalchemy_url)
    report = {}
    with engine.connect() as conn:
        report["pic_tables"] = conn.execute(text(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'pic' AND c.relkind = 'r'")).scalar()
        report["pic_tables_with_forced_rls"] = conn.execute(text(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'pic' AND c.relkind = 'r' AND c.relrowsecurity AND c.relforcerowsecurity")).scalar()
        report["pic_rows"] = {}
        for table in conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'pic' ORDER BY 1")).scalars():
            report["pic_rows"][table] = conn.execute(text(f'SELECT count(*) FROM pic."{table}"')).scalar()
        report["legacy_rows"] = {}
        for table in LEGACY_TABLES:
            exists = conn.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}).scalar()
            if exists:
                report["legacy_rows"][table] = conn.execute(text(f'SELECT count(*) FROM public."{table}"')).scalar()
    from app.pic.db import system_tx, tenant_tx
    from app.pic.models import OutboxEvent, Tenant
    from app.pic.platform.audit import verify_chain
    report["audit_chains"] = {}
    with system_tx() as s:
        tenants = [(t.id, t.code) for t in s.execute(select(Tenant)).scalars()]
    for tenant_id, code in tenants:
        with tenant_tx(tenant_id) as s:
            report["audit_chains"][code] = verify_chain(s)
            report.setdefault("pending_events", {})[code] = len(s.execute(select(OutboxEvent.id).where(OutboxEvent.published_at.is_(None))).all())
    return report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--skip-seed", action="store_true")
    parser.add_argument("--skip-legacy", action="store_true")
    parser.add_argument("--legacy-snapshot", type=Path, default=legacy_extract.SNAPSHOT)
    parser.add_argument("--fx-rate", type=Decimal, default=Decimal(1),
                        help="multiplier from legacy amounts to INR (the legacy schema has no currency column)")
    args = parser.parse_args()
    print(f"Target database: {_target()}")
    if not args.verify_only:
        print("1/4 PIC migrations …")
        migrate_pic()
        password = os.environ.get("PIC_SEED_PASSWORD")
        generated = password is None
        password = password or secrets.token_urlsafe(12)
        if not args.skip_seed:
            print("2/4 PIC seed (Axion signature case) …")
            steps = seed_pic(password)
            if steps:
                for step in steps:
                    print("   -", step)
                if generated:
                    print(f"   Demo users (…@axion.example) password: {password}  (shown once; set PIC_SEED_PASSWORD to choose it)")
        if not args.skip_legacy:
            tables, source = legacy_rows(args.legacy_snapshot)
            print(f"3/4 Legacy data from {source} …")
            migrate_legacy()
            for table, (read, inserted) in copy_legacy(tables).items():
                print(f"   public.{table:22} read {read:3}  inserted {inserted:3}")
            if args.legacy_snapshot.exists():
                for report in migrate_legacy_into_pic(args.legacy_snapshot, password, args.fx_rate):
                    if "skipped" in report:
                        print(f"   PIC tenant {report['tenant']}: {report['skipped']}")
                        continue
                    ok = all(c["ok"] for c in report["counts"] + report["values"])
                    print(f"   PIC tenant {report['tenant']} ({report['name']}): reconciliation {'OK' if ok else 'MISMATCH'}, "
                          f"{len(report['findings'])} findings, open tasks {report['openTasks']}")
                print(f"   report: {REPORT}")
                if generated:
                    print(f"   Migrated-tenant users share the password: {password}  (shown once; set PIC_SEED_PASSWORD to choose it)")
    print("4/4 Verification …")
    report = verify()
    print(f"   pic tables: {report['pic_tables']} (forced RLS on {report['pic_tables_with_forced_rls']})")
    print("   pic rows:  ", ", ".join(f"{k} {v}" for k, v in report["pic_rows"].items() if v))
    print("   legacy rows:", ", ".join(f"{k} {v}" for k, v in report["legacy_rows"].items()))
    for code, chain in report["audit_chains"].items():
        print(f"   audit chain {code}: {'valid' if chain['valid'] else 'BROKEN'} ({chain['checked']} events); pending events {report['pending_events'][code]}")
    ok = all(c["valid"] for c in report["audit_chains"].values()) and not any(report["pending_events"].values())
    print("OK" if ok else "CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
