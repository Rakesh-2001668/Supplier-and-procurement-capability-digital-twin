"""MRP scale harness: verifies the NFR "regenerative MRP run for 50,000 materials < 10 minutes".

    python -m app.pic.tools.perf_mrp --database-url postgresql://postgres@127.0.0.1:54329/pic_perf_mrp \
        --materials 50000 [--plants 1] [--demand-per-material 3] [--seed 42] [--reset] [--keep] [--profile]

What it does
1. Safety guards (exit code 2 on refusal): never a Neon URL (no override); the database name must look like a scratch
   database (perf/scratch/bench/load/tmp/temp/sandbox) unless --reset is given explicitly; the database must not hold
   tenants other than the harness tenant, nor tables outside the ``pic`` schema. DATABASE_URL is set in the
   environment before anything from ``app.pic`` is imported, so backend/.env is never used for the connection.
2. Creates the database if missing, drops the ``pic`` schema on --reset, runs the PIC migrations to head.
3. Seeds the harness tenant through the normal tenant bootstrap (number ranges, rule sets, process definitions, plants),
   then bulk-loads N materials with MRP parameters, unrestricted stock, dated demand elements and sources of supply
   (qualified suppliers, info records, source lists). Generation time is reported separately.
4. Times one regenerative MRP run per plant through the API endpoint function (``POST /v1/mrp/runs`` handler:
   tenant transaction, idempotency wrapper, ``planning.run``, response view, commit) with an MRP-controller principal.
   Reports timings, SQL statement counts by shape, planned orders / exceptions, peak RSS and PASS/FAIL.

The last stdout line is a JSON summary. Exit code 0 = PASS, 1 = FAIL (or aborted), 2 = refused / bad arguments.
Without --keep the ``pic`` schema of the scratch database is dropped at the end (not after an abort: rerun with --reset).
A run still going after --abort-after seconds (default target + 120 s) is stopped with status ABORTED; the JSON line then
carries the materials netted so far and a linear extrapolation of the full run.
"""
import argparse
import json
import os
import random
import re
import sys
import threading
import time
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[3]
HARNESS_TENANT = ("PERFMRP", "MRP scale harness (synthetic data)")
HARNESS_USER = "perf.mrp@harness.invalid"
SCRATCH_NAME = re.compile(r"(perf|scratch|bench|load|tmp|temp|sandbox)", re.IGNORECASE)
REFUSE_EXIT, FAIL_EXIT = 2, 1
CATEGORIES = [f"PERF-CAT-{i:02d}" for i in range(1, 11)]
SUPPLIER_COUNT = 8
BATCH = 5000


def refuse(message: str) -> None:
    print(f"REFUSED: {message}", file=sys.stderr)
    sys.exit(REFUSE_EXIT)


def log(message: str) -> None:
    print(f"[perf_mrp {datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


# ---------------------------------------------------------------- arguments and URL guards
def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m app.pic.tools.perf_mrp", description=__doc__.split("\n")[0])
    ap.add_argument("--database-url", help="scratch PostgreSQL URL (default: DATABASE_URL from the environment, never backend/.env)")
    ap.add_argument("--materials", type=int, default=50_000)
    ap.add_argument("--plants", type=int, default=1)
    ap.add_argument("--demand-per-material", type=int, default=3, help="average demand elements per material and plant (1..2n-1)")
    ap.add_argument("--horizon-days", type=int, default=90, help="planning horizon for generated demand")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--run-date", type=date.fromisoformat, default=None, help="MRP run date (default: today)")
    ap.add_argument("--no-sources", action="store_true", help="skip suppliers / info records / source lists")
    ap.add_argument("--reset", action="store_true", help="drop and recreate the pic schema first")
    ap.add_argument("--keep", action="store_true", help="keep the generated data (default: drop the pic schema at the end)")
    ap.add_argument("--profile", action="store_true", help="wrap the MRP run in cProfile and print the top 25 cumulative")
    ap.add_argument("--target-seconds", type=float, default=600.0)
    ap.add_argument("--abort-after", type=float, default=None,
                    help="abort a run still going after this many seconds (default: target + 120 s; 0 = never)")
    ap.add_argument("--progress-seconds", type=float, default=30.0, help="progress line interval during the MRP run")
    args = ap.parse_args(argv)
    if args.materials < 1 or args.plants < 1 or args.plants > 99 or args.demand_per_material < 1:
        ap.error("--materials >= 1, 1 <= --plants <= 99, --demand-per-material >= 1")
    if args.abort_after is None:
        args.abort_after = args.target_seconds + 120
    return args


def guard_url(args) -> "object":
    from sqlalchemy.engine import make_url

    env_url = os.environ.get("DATABASE_URL", "")
    raw = (args.database_url or env_url or "").strip()
    if not raw:
        refuse("no database URL: pass --database-url or export DATABASE_URL (backend/.env is never used by this harness)")
    for candidate in (raw, env_url if not args.database_url else ""):
        if "neon.tech" in candidate.lower():
            refuse("the URL points at Neon (neon.tech). This harness drops schemas and never runs against Neon.")
    url = make_url(raw.replace("postgres://", "postgresql://", 1) if raw.startswith("postgres://") else raw)
    if not url.drivername.startswith("postgresql"):
        refuse(f"only PostgreSQL URLs are supported (got {url.drivername})")
    name = url.database or ""
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        refuse(f"database name {name!r} must be a plain identifier")
    if name in ("postgres", "template0", "template1"):
        refuse(f"refusing to use the system database {name!r}")
    if not SCRATCH_NAME.search(name) and not args.reset:
        refuse(f"database {name!r} does not look like a scratch database (name should contain perf/scratch/bench/load/tmp); "
               "pass --reset explicitly to use it anyway")
    # Settings are cached at first import: pin the scratch URL before anything from app.pic is imported.
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    os.environ.setdefault("PIC_JWT_SECRET", "perf-harness-local-jwt-secret")
    os.environ.setdefault("PIC_FIELD_KEY", "perf-harness-local-field-key")
    return url


def psycopg_url(url) -> str:
    return url.set(drivername="postgresql+psycopg2").render_as_string(hide_password=False)


# ---------------------------------------------------------------- database preparation (plain SQLAlchemy, no app.pic)
def prepare_database(url, reset: bool) -> dict:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    name = url.database
    maint = create_engine(psycopg_url(url.set(database="postgres")), poolclass=NullPool, isolation_level="AUTOCOMMIT")
    with maint.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).first() is not None
        if not exists:
            log(f"creating database {name}")
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    maint.dispose()

    target = create_engine(psycopg_url(url), poolclass=NullPool, isolation_level="AUTOCOMMIT")
    info = {"created": not exists}
    with target.connect() as conn:
        foreign = conn.execute(text(
            "SELECT table_schema || '.' || table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pic', 'pg_catalog', 'information_schema') AND table_type = 'BASE TABLE' LIMIT 5")).scalars().all()
        if foreign:
            refuse(f"database {name!r} has tables outside the pic schema ({', '.join(foreign)}); it is not a scratch database")
        has_tenant = conn.execute(text("SELECT to_regclass('pic.tenant')")).scalar() is not None
        if has_tenant:
            others = conn.execute(text("SELECT code FROM pic.tenant WHERE code <> :c ORDER BY code LIMIT 10"),
                                  {"c": HARNESS_TENANT[0]}).scalars().all()
            if others:
                refuse(f"database {name!r} contains other tenants ({', '.join(others)}); the harness only touches a database "
                       f"holding nothing but its own tenant {HARNESS_TENANT[0]}")
        if reset:
            log("dropping schema pic (--reset)")
            conn.execute(text("DROP SCHEMA IF EXISTS pic CASCADE"))
    target.dispose()
    return info


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic_pic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "pic_migrations"))
    command.upgrade(config, "head")


def drop_schema(url) -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(psycopg_url(url), poolclass=NullPool, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS pic CASCADE"))
    engine.dispose()


# ---------------------------------------------------------------- seeding
def plant_codes(n: int) -> list[str]:
    return [f"PF{i:02d}" for i in range(1, n + 1)]


def seed_reference(plants: list[str]) -> uuid.UUID:
    """Tenant bootstrap through the product seed: process definitions, number ranges, rule sets, agents, plants."""
    import secrets

    from sqlalchemy import select

    from app.pic.db import tenant_tx
    from app.pic.models import AppUser
    from app.pic.platform.auth import hash_password
    from app.pic.seed import reference

    reference.deploy_process_definitions()
    tenant_id = reference.create_tenant(*HARNESS_TENANT)
    reference.bootstrap(tenant_id, company=("9000", "Perf Harness Manufacturing", None),
                        plants=[(code, f"Perf plant {code}", "33") for code in plants], cost_objects=[])
    reference.ensure_extensions(tenant_id)
    with tenant_tx(tenant_id) as s:
        from app.pic.models import Plant, StorageLocation
        have = set(s.execute(select(Plant.code)).scalars())
        for code in plants:  # plants added on a later run with a larger --plants
            if code not in have:
                s.add(Plant(tenant_id=tenant_id, code=code, name=f"Perf plant {code}", company_code="9000", state_code="33",
                            working_days=[0, 1, 2, 3, 4, 5], holidays=[]))
                s.add(StorageLocation(tenant_id=tenant_id, plant=code, code="0001", name="Raw material"))
        if s.execute(select(AppUser.id).where(AppUser.email == HARNESS_USER)).first() is None:
            s.add(AppUser(tenant_id=tenant_id, email=HARNESS_USER, full_name="MRP scale harness", roles=["MRP_CONTROLLER"],
                          password_hash=hash_password(secrets.token_urlsafe(24)), attributes={"plants": plants}))
    return tenant_id


def existing_counts(tenant_id: uuid.UUID) -> dict:
    from sqlalchemy import func, select

    from app.pic.db import tenant_tx
    from app.pic.models import DemandElement, InfoRecord, Material, Stock

    with tenant_tx(tenant_id) as s:
        return {"materials": s.execute(select(func.count()).select_from(Material)).scalar(),
                "demand_rows": s.execute(select(func.count()).select_from(DemandElement)).scalar(),
                "stock_rows": s.execute(select(func.count()).select_from(Stock)).scalar(),
                "info_records": s.execute(select(func.count()).select_from(InfoRecord)).scalar(),
                "demand_plants": sorted(s.execute(select(DemandElement.plant).distinct()).scalars())}


def generate(tenant_id: uuid.UUID, plants: list[str], n: int, per_material: int, horizon: int, seed: int,
             run_date: date, with_sources: bool) -> dict:
    """Bulk-load masters, stock, demand and sources with core executemany inserts on the owner connection."""
    from sqlalchemy import insert, text

    from app.pic.db import engine
    from app.pic.models import DemandElement, InfoRecord, Material, SourceList, Stock, Supplier, SupplierCategoryStatus

    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    counts = defaultdict(int)
    tid = tenant_id
    with engine().begin() as conn:
        # Owner connection; app.tenant_id is set as well so FORCE RLS policies pass for a non-superuser owner.
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        conn.execute(text("SET LOCAL synchronous_commit = off"))
        suppliers = []
        if with_sources:
            supplier_rows, status_rows = [], []
            for i in range(1, SUPPLIER_COUNT + 1):
                sid = uuid.uuid7()
                suppliers.append(sid)
                supplier_rows.append({"id": sid, "tenant_id": tid, "code": f"PSUP{i:03d}", "legal_name": f"Perf Supplier {i:03d} Pvt Ltd",
                                      "status": "QUALIFIED", "state_code": "33", "created_at": now})
                for category in CATEGORIES:
                    status_rows.append({"id": uuid.uuid7(), "tenant_id": tid, "supplier_id": sid, "category": category,
                                        "status": "QUALIFIED", "qualified_on": run_date - timedelta(days=180), "created_at": now})
            conn.execute(insert(Supplier.__table__), supplier_rows)
            conn.execute(insert(SupplierCategoryStatus.__table__), status_rows)
            counts["suppliers"] = len(supplier_rows)

        for start in range(0, n, BATCH):
            materials, stock, demand, infos, sources = [], [], [], [], []
            for k in range(start, min(n, start + BATCH)):
                mid = uuid.uuid7()
                category = CATEGORIES[k % len(CATEGORIES)]
                price = rng.randint(50, 500_000) * 100
                policy = rng.choices(("EXACT", "FIXED", "EOQ", "MINMAX"), weights=(40, 25, 15, 20))[0]
                lot_qty = Decimal(rng.choice((50, 100, 200, 250, 500))) if policy == "FIXED" else None
                annual = Decimal(rng.randint(1_000, 50_000)) if policy == "EOQ" else None
                max_lot = Decimal(rng.randint(500, 5_000)) if policy == "MINMAX" else None
                materials.append({
                    "id": mid, "tenant_id": tid, "number": f"PM-{k + 1:07d}", "description": f"Perf material {k + 1}",
                    "type": "STOCK", "material_group": f"PERF-MG-{k % len(CATEGORIES) + 1:02d}", "category": category,
                    "base_uom": "EA", "valuation_class": "3000", "hsn_code": "8708", "mrp_type": "PD",
                    "lot_size_policy": policy, "lot_size_qty": lot_qty,
                    "min_lot": Decimal(rng.choice((10, 20, 50))) if rng.random() < 0.3 else None,
                    "max_lot": max_lot, "pack_size": Decimal(rng.choice((5, 10, 25))) if rng.random() < 0.25 else None,
                    "safety_stock": Decimal(rng.randint(0, 200)), "planned_delivery_days": rng.randint(3, 45),
                    "gr_processing_days": rng.randint(0, 2), "standard_price_minor": price, "annual_demand": annual,
                    "ordering_cost_minor": 150_000 if policy == "EOQ" else None,
                    "holding_rate": Decimal("0.2000") if policy == "EOQ" else None, "status": "ACTIVE", "created_at": now,
                })
                lead = materials[-1]["planned_delivery_days"]
                for plant in plants:
                    stock.append({"id": uuid.uuid7(), "tenant_id": tid, "material_id": mid, "plant": plant, "storage_location": "0001",
                                  "stock_type": "UNRESTRICTED", "batch": "",
                                  "qty": Decimal(0) if rng.random() < 0.2 else Decimal(rng.randint(1, 800)), "created_at": now})
                    for j in range(rng.randint(1, 2 * per_material - 1)):
                        kind = rng.choices(("FORECAST", "SALES_ORDER", "RESERVATION"), weights=(60, 30, 10))[0]
                        demand.append({"id": uuid.uuid7(), "tenant_id": tid, "material_id": mid, "plant": plant, "type": kind,
                                       "reference": f"{kind[:2]}-PERF-{k + 1:07d}-{j + 1}",
                                       "req_date": run_date + timedelta(days=rng.randint(-5, horizon)),
                                       "qty": Decimal(rng.randint(10, 1_500)), "changed_at": now, "created_at": now})
                    if suppliers:
                        sid = suppliers[k % len(suppliers)]
                        infos.append({"id": uuid.uuid7(), "tenant_id": tid, "supplier_id": sid, "material_id": mid, "plant": plant,
                                      "last_price_minor": int(price * rng.uniform(0.9, 1.1)), "currency": "INR",
                                      "lead_time_days": lead, "created_at": now})
                        if rng.random() < 0.3:
                            sources.append({"id": uuid.uuid7(), "tenant_id": tid, "supplier_id": sid, "material_id": mid,
                                            "plant": plant, "fixed": True, "valid_from": run_date - timedelta(days=365),
                                            "valid_to": run_date + timedelta(days=365), "created_at": now})
            conn.execute(insert(Material.__table__), materials)
            conn.execute(insert(Stock.__table__), stock)
            conn.execute(insert(DemandElement.__table__), demand)
            if infos:
                conn.execute(insert(InfoRecord.__table__), infos)
            if sources:
                conn.execute(insert(SourceList.__table__), sources)
            counts["materials"] += len(materials)
            counts["stock_rows"] += len(stock)
            counts["demand_rows"] += len(demand)
            counts["info_records"] += len(infos)
            counts["source_lists"] += len(sources)
            log(f"  generated {counts['materials']:,}/{n:,} materials, {counts['demand_rows']:,} demand rows")
    with engine().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for table in ("material", "stock", "demand_element", "info_record", "source_list", "supplier", "supplier_category_status"):
            conn.execute(text(f"ANALYZE pic.{table}"))
    return dict(counts)


# ---------------------------------------------------------------- measurement helpers
def peak_rss_mb():
    try:
        import psutil  # optional
        info = psutil.Process().memory_info()
        peak = getattr(info, "peak_wset", None) or getattr(info, "rss", None)
        if peak:
            return round(peak / 2**20, 1)
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]

            kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return round(counters.PeakWorkingSetSize / 2**20, 1)
        else:
            import resource
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return round(peak / (2**20 if sys.platform == "darwin" else 2**10), 1)
    except Exception:
        return None
    return None


_SHAPE_TABLE = re.compile(r"\b(FROM|INTO|UPDATE)\s+pic\.(\w+)", re.IGNORECASE)


class SqlCounter:
    """Counts statements by shape (verb + first table) on the application engine while active."""

    def __init__(self, engine):
        from sqlalchemy import event

        self.active = False
        self.count = 0
        self.seconds = 0.0
        self.by_shape: dict[str, list] = defaultdict(lambda: [0, 0.0])
        self.demand_selects = 0
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._after)

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        conn.info["perf_t0"] = time.perf_counter()

    def _after(self, conn, cursor, statement, parameters, context, executemany):
        if not self.active:
            return
        elapsed = time.perf_counter() - conn.info.pop("perf_t0", time.perf_counter())
        verb = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else "?"
        match = _SHAPE_TABLE.search(statement)
        table = match.group(2) if match else "-"
        if verb == "SELECT" and table == "demand_element":
            self.demand_selects += 1
        shape = self.by_shape[f"{verb} {table}"]
        shape[0] += 1
        shape[1] += elapsed
        self.count += 1
        self.seconds += elapsed

    def top(self, n: int = 12) -> list[dict]:
        ranked = sorted(self.by_shape.items(), key=lambda kv: kv[1][1], reverse=True)[:n]
        return [{"shape": k, "count": v[0], "seconds": round(v[1], 2)} for k, v in ranked]


class Watchdog(threading.Thread):
    """Progress lines while the run is going; aborts the process past --abort-after (the open transaction rolls back)."""

    def __init__(self, counter: SqlCounter, total: int, interval: float, abort_after: float, summary: dict):
        super().__init__(daemon=True)
        self.counter, self.total, self.interval, self.abort_after, self.summary = counter, total, interval, abort_after, summary
        self.started = time.perf_counter()
        self.done = threading.Event()

    def run(self):
        while not self.done.wait(self.interval):
            elapsed = time.perf_counter() - self.started
            netted = self.counter.demand_selects
            rate = netted / elapsed if elapsed else 0
            eta = (self.total - netted) / rate if rate else float("inf")
            log(f"  progress: {netted:,}/{self.total:,} materials netted in {elapsed:,.0f}s ({rate:,.1f}/s, "
                f"~{eta:,.0f}s to go; {self.counter.count:,} SQL statements)")
            if self.abort_after and elapsed > self.abort_after:
                extrapolated = self.total / rate if rate else None
                self.summary.update({"status": "ABORTED", "aborted_after_seconds": round(elapsed, 1), "materials_netted_at_abort": netted,
                                     "extrapolated_run_seconds": round(extrapolated, 1) if extrapolated else None,
                                     "sql_statements": self.counter.count, "sql_top": self.counter.top(), "peak_rss_mb": peak_rss_mb()})
                log(f"ABORT: run exceeded {self.abort_after:.0f}s; the open MRP transaction is rolled back by the server")
                print(json.dumps(self.summary, default=str), flush=True)
                os._exit(FAIL_EXIT)


# ---------------------------------------------------------------- the timed run
def mrp_principal(tenant_id: uuid.UUID):
    from sqlalchemy import select

    from app.pic.db import tenant_tx
    from app.pic.models import AppUser
    from app.pic.platform.auth import Principal, scopes_for

    with tenant_tx(tenant_id) as s:
        user = s.execute(select(AppUser).where(AppUser.email == HARNESS_USER)).scalar_one()
        p = Principal(user_id=user.id, tenant_id=tenant_id, tenant_code=HARNESS_TENANT[0], email=user.email, name=user.full_name,
                      roles=list(user.roles), scopes=scopes_for(list(user.roles)), attributes=user.attributes or {})
    if "mrp:run" not in p.scopes:  # the endpoint's require("mrp:run")
        raise RuntimeError("harness principal lacks mrp:run")
    return p


def timed_run(principal, plant: str, run_date: date, profile: bool) -> dict:
    """Call the POST /v1/mrp/runs handler exactly as FastAPI would, with phase timers around the service and view."""
    from app.pic import views
    from app.pic.api import plan_request
    from app.pic.services import planning

    phases, captured = {}, {}
    orig_run, orig_view = planning.run, views.mrp_run

    def run_wrapper(*a, **kw):
        t0 = time.perf_counter()
        try:
            result = orig_run(*a, **kw)
            captured["run"] = result
            return result
        finally:
            phases["service_seconds"] = time.perf_counter() - t0

    def view_wrapper(*a, **kw):
        t0 = time.perf_counter()
        try:
            return orig_view(*a, **kw)
        finally:
            phases["view_seconds"] = time.perf_counter() - t0

    body = plan_request.MrpRunIn(plant=plant, mode="REGENERATIVE", run_date=run_date)
    planning.run, views.mrp_run = run_wrapper, view_wrapper
    profiler = None
    try:
        if profile:
            import cProfile
            profiler = cProfile.Profile()
        t0 = time.perf_counter()
        if profiler:
            response = profiler.runcall(plan_request.start_mrp_run, body, p=principal, key=None)
        else:
            response = plan_request.start_mrp_run(body, p=principal, key=None)
        total = time.perf_counter() - t0
    finally:
        planning.run, views.mrp_run = orig_run, orig_view
    run = captured["run"]
    result = {
        "plant": plant, "run": run.number, "status": run.status, "total_seconds": round(total, 3),
        "service_seconds": round(phases.get("service_seconds", 0), 3), "view_seconds": round(phases.get("view_seconds", 0), 3),
        "commit_and_serialise_seconds": round(total - phases.get("service_seconds", 0) - phases.get("view_seconds", 0), 3),
        "materials_planned": run.materials_planned, "planned_orders": run.planned_orders_created,
        "exceptions": run.exceptions_raised, "response_planned_orders": len(response.get("plannedOrders", [])),
    }
    if profiler:
        import io
        import pstats
        out = io.StringIO()
        pstats.Stats(profiler, stream=out).sort_stats("cumulative").print_stats(25)
        print(f"\n---- cProfile (plant {plant}): top 25 by cumulative time ----\n{out.getvalue()}", flush=True)
    return result


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    url = guard_url(args)  # sets DATABASE_URL before any app.pic import
    safe_url = url.render_as_string(hide_password=True)
    log(f"target {safe_url}: {args.materials:,} materials x {args.plants} plant(s), ~{args.demand_per_material} demand/material")

    db_info = prepare_database(url, args.reset)
    t0 = time.perf_counter()
    migrate()
    migrate_seconds = time.perf_counter() - t0

    from app.pic.config import get_settings
    settings = get_settings()
    if "neon.tech" in settings.database_url.lower() or settings.database_url != os.environ["DATABASE_URL"]:
        refuse("application settings did not pick up the scratch DATABASE_URL")
    import app.pic.services  # noqa: F401  (registers handlers, as the API and worker do)
    from app.pic.db import engine
    from app.pic.platform import clock

    run_date = args.run_date or clock.today()
    plants = plant_codes(args.plants)

    t0 = time.perf_counter()
    tenant_id = seed_reference(plants)
    reference_seconds = time.perf_counter() - t0

    have = existing_counts(tenant_id)
    reused = False
    if have["materials"] == 0:
        log(f"generating {args.materials:,} materials (seed {args.seed}, run date {run_date})")
        t0 = time.perf_counter()
        counts = generate(tenant_id, plants, args.materials, args.demand_per_material, args.horizon_days, args.seed, run_date,
                          not args.no_sources)
        generation_seconds = time.perf_counter() - t0
    elif have["materials"] == args.materials and set(plants) <= set(have["demand_plants"]):
        reused, generation_seconds = True, 0.0
        counts = {k: v for k, v in have.items() if k != "demand_plants"}
        log(f"reusing the {have['materials']:,} materials already generated (pass --reset to regenerate)")
    else:
        refuse(f"the harness tenant already holds {have['materials']:,} materials for plants {have['demand_plants']}; "
               f"pass --reset to regenerate {args.materials:,} materials for {plants}")
    log(f"data ready: {counts}; generation {generation_seconds:,.1f}s")

    principal = mrp_principal(tenant_id)
    counter = SqlCounter(engine())
    summary = {"status": "RUNNING", "target_seconds": args.target_seconds, "materials": args.materials, "plants": args.plants,
               "demand_rows": counts.get("demand_rows"), "generation_seconds": round(generation_seconds, 2), "database": safe_url}
    runs = []
    for plant in plants:
        log(f"regenerative MRP run, plant {plant}, run date {run_date}")
        counter.demand_selects = 0
        watchdog = Watchdog(counter, args.materials, args.progress_seconds, args.abort_after, dict(summary, plant=plant))
        counter.active = True
        watchdog.start()
        try:
            result = timed_run(principal, plant, run_date, args.profile)
        finally:
            watchdog.done.set()
            counter.active = False
        runs.append(result)
        log(f"  {result}")

    mrp_seconds = sum(r["total_seconds"] for r in runs)
    planned = sum(r["materials_planned"] for r in runs)
    passed = mrp_seconds <= args.target_seconds
    summary.update({
        "status": "PASS" if passed else "FAIL",
        "stock_rows": counts.get("stock_rows"), "info_records": counts.get("info_records"), "source_lists": counts.get("source_lists"),
        "reused_data": reused, "database_created": db_info["created"], "migrate_seconds": round(migrate_seconds, 2),
        "reference_seed_seconds": round(reference_seconds, 2),
        "mrp_seconds": round(mrp_seconds, 3), "service_seconds": round(sum(r["service_seconds"] for r in runs), 3),
        "view_seconds": round(sum(r["view_seconds"] for r in runs), 3),
        "materials_per_second": round(planned / mrp_seconds, 1) if mrp_seconds else None,
        "materials_planned": planned, "planned_orders": sum(r["planned_orders"] for r in runs),
        "exceptions": sum(r["exceptions"] for r in runs),
        "sql_statements": counter.count, "sql_seconds": round(counter.seconds, 2),
        "sql_statements_per_material": round(counter.count / planned, 1) if planned else None,
        "linear_extrapolation_50k_seconds": round(mrp_seconds / planned * 50_000, 1) if planned else None,
        # Lower bound only: per-material cost grows with table size (unindexed per-material lookups), so real 50k is slower.
        "projected_50k_status": ("PASS" if planned and mrp_seconds / planned * 50_000 <= args.target_seconds else "FAIL"),
        "sql_top": counter.top(), "peak_rss_mb": peak_rss_mb(), "runs": runs,
    })
    log("SQL by shape (count, seconds): " + "; ".join(f"{t['shape']} {t['count']:,} {t['seconds']}s" for t in summary["sql_top"]))
    log(f"{summary['status']}: {mrp_seconds:,.1f}s for {planned:,} material-plant(s) "
        f"({summary['materials_per_second']}/s) against a target of {args.target_seconds:,.0f}s")

    if not args.keep:
        engine().dispose()
        drop_schema(url)
        log("dropped schema pic (pass --keep to keep the generated data)")
    print(json.dumps(summary, default=str), flush=True)
    return 0 if passed else FAIL_EXIT


if __name__ == "__main__":
    sys.exit(main())
