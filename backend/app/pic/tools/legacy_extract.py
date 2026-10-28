"""Extract the legacy supplier_twin database into a versioned JSON snapshot.

    python -m app.pic.tools.legacy_extract                                  # Docker container supplier_twin_db
    python -m app.pic.tools.legacy_extract --container NAME --db DB --user USER
    python -m app.pic.tools.legacy_extract --url postgresql://...           # any reachable PostgreSQL (read-only session)
    python -m app.pic.tools.legacy_extract --sqlite backend/capability_twin.db

The snapshot (backend/data/legacy/supplier_twin.json) is what neon_setup loads, so the Neon
load does not need Docker. Reads only: the Docker path runs psql inside the container as the
database owner, the URL path opens a read-only transaction. No credentials are written.
"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.pic.config import BACKEND_DIR

SNAPSHOT = BACKEND_DIR / "data" / "legacy" / "supplier_twin.json"

# Parent tables first so foreign keys resolve when the snapshot is replayed.
TABLES = ["tenants", "users", "supplier_profiles", "order_requests", "quotations", "negotiation_messages", "purchase_orders",
          "po_approvals", "contracts", "advance_ship_notices", "goods_receipts", "sales_invoices", "payments", "inventory_items",
          "stock_transactions"]
KEYS = {"supplier_profiles": "tenant_id"}


def _rows_sql(table: str) -> str:
    key = KEYS.get(table, "id")
    return f"SELECT coalesce(json_agg(t ORDER BY t.{key}), '[]'::json) FROM public.{table} t"


def _columns_sql() -> str:
    return ("SELECT coalesce(json_object_agg(table_name, cols), '{}'::json) FROM (SELECT table_name, "
            "json_agg(json_build_object('name', column_name, 'type', data_type) ORDER BY ordinal_position) cols "
            "FROM information_schema.columns WHERE table_schema = 'public' GROUP BY table_name) x")


def from_docker(container: str, db: str, user: str) -> tuple[dict, dict, str]:
    def query(sql: str):
        out = subprocess.run(["docker", "exec", container, "psql", "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1", "-tAc", sql],
                             capture_output=True, text=True, encoding="utf-8", check=True)
        return json.loads(out.stdout)
    columns = query(_columns_sql())
    tables = {t: query(_rows_sql(t)) for t in TABLES if t in columns}
    version = query("SELECT to_json(version_num) FROM alembic_version LIMIT 1") if "alembic_version" in columns else None
    return tables, columns, version


def from_url(url: str) -> tuple[dict, dict, str]:
    from sqlalchemy import create_engine, text
    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://", 1) if url.startswith("postgresql://") else url)
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        columns = conn.execute(text(_columns_sql())).scalar()
        tables = {t: conn.execute(text(_rows_sql(t))).scalar() for t in TABLES if t in columns}
        version = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar() if "alembic_version" in columns else None
    return tables, columns, version


def from_sqlite(path: Path) -> tuple[dict, dict, str]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    present = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    columns, tables = {}, {}
    for table in TABLES:
        if table not in present:
            continue
        columns[table] = [{"name": r["name"], "type": r["type"]} for r in con.execute(f'PRAGMA table_info("{table}")')]
        tables[table] = [dict(r) for r in con.execute(f'SELECT * FROM "{table}" ORDER BY {KEYS.get(table, "id")}')]
    version = con.execute("SELECT version_num FROM alembic_version").fetchone()[0] if "alembic_version" in present else None
    return tables, columns, version


def write(tables: dict, columns: dict, version: str, source: dict, path: Path = SNAPSHOT) -> dict:
    body = json.dumps(tables, sort_keys=True, ensure_ascii=False, default=str)
    snapshot = {
        "source": source, "extractedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "alembicVersion": version,
        "counts": {t: len(rows) for t, rows in tables.items()}, "sha256": hashlib.sha256(body.encode()).hexdigest(),
        "columns": {t: columns[t] for t in tables}, "tables": tables,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return snapshot


def load(path: Path = SNAPSHOT) -> dict:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    body = json.dumps(snapshot["tables"], sort_keys=True, ensure_ascii=False, default=str)
    if hashlib.sha256(body.encode()).hexdigest() != snapshot["sha256"]:
        raise ValueError(f"{path} does not match its checksum; re-extract it")
    return snapshot


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--container", default="supplier_twin_db")
    parser.add_argument("--db", default="supplier_twin")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--url", help="read from this PostgreSQL URL instead of Docker")
    parser.add_argument("--sqlite", type=Path, help="read from this SQLite file instead of Docker")
    parser.add_argument("--out", type=Path, default=SNAPSHOT)
    args = parser.parse_args()
    if args.sqlite:
        tables, columns, version = from_sqlite(args.sqlite)
        source = {"kind": "sqlite", "file": args.sqlite.name}
    elif args.url:
        tables, columns, version = from_url(args.url)
        source = {"kind": "postgresql", "host": args.url.split("@")[-1].split("?")[0]}
    else:
        tables, columns, version = from_docker(args.container, args.db, args.user)
        source = {"kind": "docker", "container": args.container, "database": args.db}
    snapshot = write(tables, columns, version, source, args.out)
    print(f"Extracted {sum(snapshot['counts'].values())} rows from {source} (alembic {version}) → {args.out}")
    for table, count in snapshot["counts"].items():
        print(f"   {table:22} {count:4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
