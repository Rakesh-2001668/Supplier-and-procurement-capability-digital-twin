"""NFR volume generator (D8, Technical Document §15): 50,000 materials, 5 M invoices a year, 50 M spend lines, scaled by a factor.

    python -m app.pic.tools.volume_gen --database-url postgresql://postgres@127.0.0.1:54329/pic_scratch_volume \
        --scale 1.0 [--years 1] [--seed 7] [--reset] [--keep] [--measure] [--measure-mrp]

Scale 1.0 is the NFR volume: 50,000 materials (MRP), 2,000 suppliers, 5,000,000 invoices in --years 1 with ~2 lines each
(2,500,000 POs with 1–3 lines, two invoices per PO), 50,000,000 spend lines in total (one per invoice line, the rest as ERP
spend history over the three years before). --scale 0.001 gives 50 materials, 5,000 invoices and 50,000 spend lines.

Safety and reuse: everything that prepares the database comes from the MRP scale harness (``tools.perf_mrp``): a Neon URL is
always refused (exit 2), the database name must look like a scratch database (perf/scratch/bench/load/tmp/temp/sandbox) unless
--reset is given, the database must hold no tenant other than the harness tenant PERFMRP and no tables outside ``pic``.
The tenant bootstrap and the 50,000 materials with stock, demand and sources of supply are the harness's own seeding
(``perf_mrp.seed_reference`` / ``perf_mrp.generate``), so ``perf_mrp`` can time MRP on the same data afterwards. The
transaction volume (suppliers, POs, PO lines, invoices, invoice lines, spend lines) is written with PostgreSQL COPY into the
same tables the services use (straight COPY when the connecting role bypasses RLS, otherwise COPY into a temporary staging
table and INSERT … SELECT under the tenant's RLS context).

--measure times the spend cube (savings.spend_cube, the SPD/Copilot aggregation) by category, by supplier and by
category × period through the service functions with a category-manager principal, against the NFR "spend cube query < 3 s on
50 M lines"; --measure-mrp also times one regenerative MRP run per plant (perf_mrp.timed_run, target < 10 min for 50,000
materials). The last stdout line is a JSON summary. Without --keep the pic schema is dropped at the end.
"""
import argparse
import csv
import io
import json
import random
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.pic.tools import perf_mrp

NFR = {"materials": 50_000, "suppliers": 2_000, "invoices_per_year": 5_000_000, "spend_lines": 50_000_000}
CUBE_TARGET_SECONDS = 3.0
CHUNK = 50_000
COMPANY = "9000"
CUBE_USER = "perf.cube@harness.invalid"
# Default manufacturing categories with an HSN/SAC code each (GST 18% under the CBIC schedule, data/reference).
CATEGORIES = [("ALU-DIECAST", "87089900", "Aluminium die-cast housing"), ("FORGINGS", "73269099", "Steel forging"),
              ("MACHINING", "84839000", "CNC machined shaft"), ("RAW-MATERIALS", "76012010", "Aluminium alloy ingot"),
              ("FASTENERS", "73181500", "Hex bolt zinc flake"), ("ELECTRONICS", "85369090", "Sealed connector"),
              ("RUBBER-SEALS", "40169320", "O-ring NBR"), ("PACKAGING", "48191010", "Corrugated carton"),
              ("TOOLING-SERVICES", "998717", "Die maintenance visit"), ("LOGISTICS", "996791", "FTL freight"),
              ("MRO", "84821011", "Ball bearing"), ("IT-SERVICES", "998313", "IT support"), ("FACILITIES", "998533", "Housekeeping"),
              ("PROF-SERVICES", "998311", "Management consulting")]
CHANNELS = ("E_INVOICE", "E_INVOICE", "PORTAL", "EDI", "PDF_OCR")


def log(message: str) -> None:
    print(f"[volume_gen {datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m app.pic.tools.volume_gen", description=__doc__.split("\n")[0])
    ap.add_argument("--database-url", help="scratch PostgreSQL URL (default DATABASE_URL; never backend/.env; Neon is refused)")
    ap.add_argument("--scale", type=float, default=1.0, help="1.0 = NFR volume (50k materials, 5 M invoices/year, 50 M spend lines)")
    ap.add_argument("--years", type=int, default=1, help="years of invoices at 5 M/year x scale")
    ap.add_argument("--plants", type=int, default=1)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--run-date", type=date.fromisoformat, default=None, help="end of the generated history (default today)")
    ap.add_argument("--reset", action="store_true", help="drop and recreate the pic schema first")
    ap.add_argument("--keep", action="store_true", help="keep the generated data (default: drop the pic schema at the end)")
    ap.add_argument("--measure", action="store_true", help="time the spend cube through the service functions")
    ap.add_argument("--measure-mrp", action="store_true", help="also time one regenerative MRP run per plant (perf_mrp)")
    args = ap.parse_args(argv)
    if not 0 < args.scale <= 10 or args.years < 1 or not 1 <= args.plants <= 99:
        ap.error("0 < --scale <= 10, --years >= 1, 1 <= --plants <= 99")
    return args


def volumes(scale: float, years: int) -> dict:
    invoices = max(10, int(NFR["invoices_per_year"] * scale * years))
    invoices -= invoices % 2  # two invoices per PO
    return {"materials": max(10, int(NFR["materials"] * scale)), "suppliers": max(10, int(NFR["suppliers"] * scale)),
            "purchase_orders": invoices // 2, "invoices": invoices, "spend_lines": max(invoices * 2, int(NFR["spend_lines"] * scale))}


# ---------------------------------------------------------------- COPY
NULL = r"\N"


def _formatter(col):
    """One text formatter per column type (COPY csv with NULL '\\N')."""
    from sqlalchemy import Boolean, Date, DateTime
    from sqlalchemy.dialects.postgresql import ARRAY, JSONB

    kind = col.type
    if isinstance(kind, JSONB):
        return lambda v: NULL if v is None else json.dumps(v, separators=(",", ":"), default=str)
    if isinstance(kind, Boolean):
        return lambda v: NULL if v is None else ("t" if v else "f")
    if isinstance(kind, ARRAY):
        return lambda v: NULL if v is None else "{" + ",".join(str(x) for x in v) + "}"
    if isinstance(kind, (Date, DateTime)):
        return lambda v: NULL if v is None else v.isoformat()
    return lambda v: NULL if v is None else str(v)


class Copier:
    """COPY rows into a pic table: direct when the role bypasses RLS, else via a temporary staging table under RLS."""

    def __init__(self, engine, tenant_id: uuid.UUID):
        self.engine, self.tenant_id = engine, tenant_id
        with engine.connect() as conn:
            from sqlalchemy import text
            self.bypass = bool(conn.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")).scalar())
        self.counts: dict[str, int] = {}
        self.seconds: dict[str, float] = {}

    def plan(self, table, sample: dict) -> list[tuple]:
        """(column, formatter, constant default cell or None) for every column the COPY writes."""
        out = []
        for col in table.columns:
            fmt = _formatter(col)
            if col.name in sample:
                out.append((col, fmt, None))
            elif col.default is not None and col.server_default is None:
                if col.primary_key:
                    raise ValueError(f"{table.name}.{col.name}: primary keys are generated by the caller")
                arg = col.default.arg
                out.append((col, fmt, fmt(arg(None) if callable(arg) else arg)))
            elif not col.nullable and col.server_default is None:
                raise ValueError(f"{table.name}.{col.name} is NOT NULL and has no value or default")
        return out

    def copy(self, table, rows: list[dict]) -> None:
        if not rows:
            return
        plan = self.plan(table, rows[0])
        cols = [c for c, _, _ in plan]
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerows([fmt(row[col.name]) if const is None else const for col, fmt, const in plan] for row in rows)
        buf.seek(0)
        t0 = time.perf_counter()
        names = ", ".join(f'"{c.name}"' for c in cols)
        raw = self.engine.raw_connection()
        try:
            cur = raw.cursor()
            cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(self.tenant_id),))
            cur.execute("SET synchronous_commit = off")
            if self.bypass:
                cur.copy_expert(f"COPY pic.{table.name} ({names}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)
            else:
                cur.execute(f"CREATE TEMP TABLE stg_{table.name} (LIKE pic.{table.name} INCLUDING DEFAULTS) ON COMMIT DROP")
                cur.copy_expert(f"COPY stg_{table.name} ({names}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)
                cur.execute(f"INSERT INTO pic.{table.name} ({names}) SELECT {names} FROM stg_{table.name}")
            raw.commit()
        finally:
            raw.close()
        self.counts[table.name] = self.counts.get(table.name, 0) + len(rows)
        self.seconds[table.name] = self.seconds.get(table.name, 0.0) + time.perf_counter() - t0


# ---------------------------------------------------------------- generation
def _period(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def generate_transactions(engine, tenant_id: uuid.UUID, plants: list[str], vol: dict, seed: int, run_date: date, years: int) -> dict:
    from sqlalchemy import select

    from app.pic.db import tenant_tx
    from app.pic.models import Invoice, InvoiceLine, Material, PoLine, PurchaseOrder, SpendLine, Supplier, SupplierCategoryStatus
    from app.pic.platform import clock

    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    copier = Copier(engine, tenant_id)
    with tenant_tx(tenant_id) as s:
        material_ids = [(m.id, m.category) for m in s.execute(select(Material).order_by(Material.number)).scalars()]
    # suppliers: ~1,000 per category share, each qualified for one or two categories
    suppliers, statuses = [], []
    for i in range(1, vol["suppliers"] + 1):
        sid = uuid.uuid7()
        cats = sorted({CATEGORIES[i % len(CATEGORIES)][0], CATEGORIES[(i * 7) % len(CATEGORIES)][0]})
        suppliers.append({"id": sid, "tenant_id": tenant_id, "code": f"VS-{i:06d}", "legal_name": f"Volume Supplier {i:06d} Pvt Ltd",
                          "status": "QUALIFIED", "state_code": "33", "country": "IN", "payment_terms": rng.choice(("N30", "N45", "N60")),
                          "screening": {"outcome": "CLEAR", "source": "VOLUME_GEN"}, "address": {}, "punchout": {}, "order_channel": {},
                          "created_at": now, "row_version": 1, "_cats": cats})
        for cat in cats:
            statuses.append({"id": uuid.uuid7(), "tenant_id": tenant_id, "supplier_id": sid, "category": cat, "status": "QUALIFIED",
                             "qualified_on": run_date - timedelta(days=400), "created_at": now, "row_version": 1})
    copier.copy(Supplier.__table__, [{k: v for k, v in r.items() if k != "_cats"} for r in suppliers])
    copier.copy(SupplierCategoryStatus.__table__, statuses)
    log(f"  {len(suppliers):,} suppliers")
    by_cat = {c: [r for r in suppliers if c in r["_cats"]] or suppliers for c, _, _ in CATEGORIES}
    start = run_date - timedelta(days=365 * years)
    span = (run_date - start).days
    pos, po_lines, invoices, inv_lines, spend = [], [], [], [], []
    n_inv = 0

    def flush(final=False):
        for table, rows in ((PurchaseOrder.__table__, pos), (PoLine.__table__, po_lines), (Invoice.__table__, invoices),
                            (InvoiceLine.__table__, inv_lines), (SpendLine.__table__, spend)):
            if rows and (final or len(rows) >= CHUNK):
                copier.copy(table, rows)
                rows.clear()

    for n in range(1, vol["purchase_orders"] + 1):
        cat, hsn, text = CATEGORIES[rng.randrange(len(CATEGORIES))]
        sup = rng.choice(by_cat[cat])
        plant = plants[n % len(plants)]
        po_day = start + timedelta(days=rng.randrange(max(1, span - 30)))
        po_id = uuid.uuid7()
        lines, total = [], 0
        for line_no in range(10, 10 * (1 + rng.choice((1, 1, 2, 2, 3))), 10):
            material = rng.choice(material_ids)[0] if material_ids and cat in ("ALU-DIECAST", "FORGINGS", "MACHINING", "FASTENERS") else None
            qty = Decimal(rng.choice((2, 10, 40, 100, 400, 1000)))
            price = rng.randint(50, 250_000) * 100 if qty <= 40 else rng.randint(5, 2_000) * 100
            net = int(qty * price)
            total += net
            lines.append({"id": uuid.uuid7(), "tenant_id": tenant_id, "po_id": po_id, "line_no": line_no,
                          "item_type": "MATERIAL" if material else "SERVICE" if hsn.startswith("99") else "FREE_TEXT",
                          "purchase_type": "SERVICE" if hsn.startswith("99") else "STOCK" if material else "NON_STOCK",
                          "material_id": material, "description": f"{text} {n}-{line_no}", "material_group": cat, "qty": qty, "uom": "EA",
                          "unit_price_minor": price, "net_minor": net, "gst_rate": Decimal(18), "hsn_code": hsn,
                          "need_date": po_day + timedelta(days=21), "plant": plant, "gr_required": not hsn.startswith("99"),
                          "ir_required": True, "ses_required": hsn.startswith("99"), "ers": False, "quality_managed": False,
                          "price_source": rng.choice(("CONTRACT", "INFO_RECORD", "CATALOGUE", "QUOTE")), "price_deviation": False,
                          "received_qty": qty, "accepted_qty": qty, "rejected_qty": Decimal(0), "shipped_qty": qty, "invoiced_qty": qty,
                          "invoiced_minor": net, "ses_approved_minor": net if hsn.startswith("99") else 0, "created_at": now, "row_version": 1})
        pos.append({"id": po_id, "tenant_id": tenant_id, "number": f"VPO-{n:09d}", "version": 1, "company_code": COMPANY, "purch_org": COMPANY,
                    "plant": plant, "supplier_id": sup["id"], "status": "INVOICED", "purpose_code": "STOCK", "currency": "INR",
                    "total_minor": total, "payment_terms": sup["payment_terms"], "tolerance": {}, "inherited": {}, "overrides": [],
                    "risk_factors": [], "touchless_reasons": [], "touchless": rng.random() < 0.6, "rule_set_version": "VOLUME-GEN",
                    "released_at": datetime.combine(po_day, datetime.min.time(), timezone.utc), "created_at": now, "row_version": 1})
        po_lines.extend(lines)
        contracted = lines[0]["price_source"] == "CONTRACT"
        for half in (0, 1):  # two invoices per PO, each for half of every line
            n_inv += 1
            inv_day = min(run_date, po_day + timedelta(days=20 + 10 * half + rng.randrange(10)))
            inv_id = uuid.uuid7()
            net_total = tax_total = 0
            for line in lines:
                qty = line["qty"] / 2
                net = int(qty * line["unit_price_minor"])
                tax = int((Decimal(net) * Decimal("0.18")).quantize(Decimal("1")))
                net_total, tax_total = net_total + net, tax_total + tax
                il_id = uuid.uuid7()
                inv_lines.append({"id": il_id, "tenant_id": tenant_id, "invoice_id": inv_id, "line_no": line["line_no"], "po_line_id": line["id"],
                                  "description": line["description"], "qty": qty, "unit_price_minor": line["unit_price_minor"], "net_minor": net,
                                  "hsn_code": line["hsn_code"], "gst_rate": Decimal(18), "tax_minor": tax, "match_status": "OK", "match_detail": {},
                                  "created_at": now, "row_version": 1})
                spend.append({"id": uuid.uuid7(), "tenant_id": tenant_id, "invoice_line_id": il_id, "invoice_ref": f"VINV-{n_inv:09d}",
                              "po_ref": f"VPO-{n:09d}", "supplier_id": sup["id"], "category": cat, "material_group": cat, "plant": plant,
                              "company_code": COMPANY, "cost_object": None, "period": _period(inv_day), "amount_minor": net, "currency": "INR",
                              "contracted": contracted, "addressable": True, "maverick_flags": [] if rng.random() > 0.05 else ["OFF_CONTRACT"],
                              "classification_confidence": Decimal("1.000"), "description": line["description"], "po_line_id": line["id"],
                              "price_variance_minor": 0, "source": "PLATFORM", "created_at": now, "row_version": 1})
            invoices.append({"id": inv_id, "tenant_id": tenant_id, "number": f"VINV-{n_inv:09d}", "supplier_invoice_no": f"S{n_inv:09d}",
                             "fiscal_year": clock.fiscal_year(inv_day), "company_code": COMPANY, "supplier_id": sup["id"], "po_id": po_id,
                             "invoice_date": inv_day, "channel": rng.choice(CHANNELS), "currency": "INR", "net_minor": net_total,
                             "tax_minor": tax_total, "gross_minor": net_total + tax_total, "status": "PAID" if inv_day < run_date - timedelta(days=60) else "POSTED",
                             "match_type": "SES" if lines[0]["ses_required"] else "3WAY", "first_pass_matched": rng.random() < 0.85,
                             "payment_block": False, "retention_minor": 0, "payment_status": "PAID" if inv_day < run_date - timedelta(days=60) else "UNPAID",
                             "due_date": inv_day + timedelta(days=45), "rule_set_version": "VOLUME-GEN", "created_at": now, "row_version": 1})
        flush()
        if n % 250_000 == 0:
            log(f"  {n:,}/{vol['purchase_orders']:,} POs, {n_inv:,} invoices")
    flush(final=True)
    platform_lines = copier.counts.get("spend_line", 0)
    # ERP spend history (three years before the invoices) up to the total spend-line volume
    history = max(0, vol["spend_lines"] - platform_lines)
    hist_start = start - timedelta(days=365 * 3)
    for k in range(1, history + 1):
        cat, _, text = CATEGORIES[rng.randrange(len(CATEGORIES))]
        sup = rng.choice(by_cat[cat])
        day = hist_start + timedelta(days=rng.randrange(365 * 3))
        ref = f"ERPV-{k:010d}"
        spend.append({"id": uuid.uuid7(), "tenant_id": tenant_id, "invoice_line_id": uuid.uuid7(), "invoice_ref": ref, "po_ref": None,
                      "supplier_id": sup["id"], "category": cat, "material_group": cat, "plant": plants[k % len(plants)], "company_code": COMPANY,
                      "cost_object": None, "period": _period(day), "amount_minor": rng.randint(1_000, 5_000_000) * 100, "currency": "INR",
                      "contracted": rng.random() < 0.7, "addressable": True, "maverick_flags": [], "classification_confidence": Decimal("1.000"),
                      "description": f"{text} (ERP history)", "price_variance_minor": 0, "source": "ERP_HISTORY", "created_at": now, "row_version": 1})
        if len(spend) >= CHUNK:
            copier.copy(SpendLine.__table__, spend)
            spend.clear()
        if k % 1_000_000 == 0:
            log(f"  {k:,}/{history:,} ERP history spend lines")
    copier.copy(SpendLine.__table__, spend)
    return dict(copier.counts, copy_mode="direct" if copier.bypass else "staging+insert",
                copy_server_seconds={k: round(v, 2) for k, v in copier.seconds.items()})


def analyze(engine) -> None:
    from sqlalchemy import text
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for table in ("supplier", "supplier_category_status", "purchase_order", "po_line", "invoice", "invoice_line", "spend_line"):
            conn.execute(text(f"ANALYZE pic.{table}"))


# ---------------------------------------------------------------- measurement
def cube_principal(tenant_id: uuid.UUID):
    import secrets

    from sqlalchemy import select

    from app.pic.db import tenant_tx
    from app.pic.models import AppUser
    from app.pic.platform.auth import Principal, hash_password, scopes_for

    with tenant_tx(tenant_id) as s:
        user = s.execute(select(AppUser).where(AppUser.email == CUBE_USER)).scalar_one_or_none()
        if user is None:
            user = AppUser(tenant_id=tenant_id, email=CUBE_USER, full_name="Spend cube harness", roles=["CATEGORY_MANAGER"],
                           password_hash=hash_password(secrets.token_urlsafe(24)), attributes={})
            s.add(user)
            s.flush()
        return Principal(user_id=user.id, tenant_id=tenant_id, tenant_code=perf_mrp.HARNESS_TENANT[0], email=user.email, name=user.full_name,
                         roles=list(user.roles), scopes=scopes_for(list(user.roles)), attributes={})


def measure_cube(tenant_id: uuid.UUID) -> list[dict]:
    from app.pic.db import tenant_tx
    from app.pic.services import savings

    principal = cube_principal(tenant_id)
    out = []
    for dims in (["category"], ["supplier"], ["category", "period"]):
        with tenant_tx(tenant_id, principal.user_id, principal) as s:
            t0 = time.perf_counter()
            cube = savings.spend_cube(s, dims)
            seconds = time.perf_counter() - t0
        out.append({"dimensions": dims, "seconds": round(seconds, 3), "rows": len(cube["rows"]),
                    "lines": sum(r["lines"] for r in cube["rows"]), "pass": seconds <= CUBE_TARGET_SECONDS})
        log(f"  spend cube {dims}: {seconds:,.2f}s, {len(cube['rows']):,} rows")
    return out


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    raw = (args.database_url or "").lower()
    if "neon.tech" in raw:
        perf_mrp.refuse("the URL points at Neon (neon.tech). The volume generator never runs against Neon.")
    url = perf_mrp.guard_url(args)  # refuses Neon / non-scratch names; pins DATABASE_URL before app.pic is imported
    safe_url = url.render_as_string(hide_password=True)
    vol = volumes(args.scale, args.years)
    log(f"target {safe_url}: scale {args.scale} → {vol}")
    db_info = perf_mrp.prepare_database(url, args.reset)
    perf_mrp.migrate()

    from app.pic.config import get_settings
    if "neon.tech" in get_settings().database_url.lower():
        perf_mrp.refuse("application settings point at Neon")
    import app.pic.services  # noqa: F401
    from app.pic.db import engine
    from app.pic.platform import clock

    run_date = args.run_date or clock.today()
    plants = perf_mrp.plant_codes(args.plants)
    tenant_id = perf_mrp.seed_reference(plants)
    have = perf_mrp.existing_counts(tenant_id)
    if have["materials"]:
        perf_mrp.refuse(f"the harness tenant already holds {have['materials']:,} materials; pass --reset to regenerate")
    summary = {"status": "RUNNING", "scale": args.scale, "years": args.years, "volumes": vol, "database": safe_url,
               "database_created": db_info["created"]}
    t0 = time.perf_counter()
    log(f"materials, stock, demand and sources through the MRP harness ({vol['materials']:,} materials)")
    summary["mrp_masters"] = perf_mrp.generate(tenant_id, plants, vol["materials"], 3, 90, args.seed, run_date, True)
    summary["mrp_masters_seconds"] = round(time.perf_counter() - t0, 2)
    t0 = time.perf_counter()
    log("transactions by COPY: suppliers, POs, PO lines, invoices, invoice lines, spend lines")
    summary["copied"] = generate_transactions(engine(), tenant_id, plants, vol, args.seed, run_date, args.years)
    analyze(engine())
    summary["copy_seconds"] = round(time.perf_counter() - t0, 2)
    summary["rows_per_second"] = round(sum(v for k, v in summary["copied"].items() if isinstance(v, int)) / summary["copy_seconds"], 1)
    passed = True
    if args.measure or args.measure_mrp:
        summary["spend_cube"] = measure_cube(tenant_id)
        passed = all(r["pass"] for r in summary["spend_cube"])
    if args.measure_mrp:
        principal = perf_mrp.mrp_principal(tenant_id)
        summary["mrp_runs"] = [perf_mrp.timed_run(principal, plant, run_date, False) for plant in plants]
        mrp_seconds = sum(r["total_seconds"] for r in summary["mrp_runs"])
        summary["mrp_seconds"] = round(mrp_seconds, 2)
        passed = passed and mrp_seconds <= 600
    summary["status"] = "PASS" if passed else "FAIL"
    if not args.keep:
        engine().dispose()
        perf_mrp.drop_schema(url)
        log("dropped schema pic (pass --keep to keep the generated data)")
    print(json.dumps(summary, default=str), flush=True)
    return 0 if passed else perf_mrp.FAIL_EXIT


if __name__ == "__main__":
    sys.exit(main())
