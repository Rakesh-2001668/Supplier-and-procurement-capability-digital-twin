# AlphaHelion Purchasing Intelligence Cloud

Governed procure-to-pay on one data foundation. The nine Blueprint flows F1–F9 run on PostgreSQL (Neon), from MRP to realised savings. AI recommends. Humans decide.

| Part | Path | What it is |
|---|---|---|
| API | `backend/app/pic` | FastAPI, `/v1` command and query API (OpenAPI at `/docs`) |
| Worker | `backend/app/pic/worker.py` | Outbox relay, workflow timers, ERP retries |
| Database | schema `pic` | 101 tables; row-level security per tenant; append-only hash-chained audit |
| Web workspace | `frontend/src/app/pic` | Next.js 16 screens for every module, plus the supplier portal |
| Legacy demo | `backend/app/routers`, `frontend/src/app/*` | Earlier prototype screens, kept until retired |
| Legacy data | `backend/data/legacy/supplier_twin.json` | Snapshot of the Docker `supplier_twin` database, loaded by `neon_setup` |
| Docs | `docs/` | Delivery plan, process flows (F1–F9 and the intelligence modules as implemented), module gap analysis against the blueprint, legacy migration report |

## Run locally

```bash
# API (Python 3.12+)
cd backend
cp .env.example .env            # set DATABASE_URL, PIC_JWT_SECRET, PIC_FIELD_KEY
python -m venv venv && venv/Scripts/pip install -r requirements.txt
venv/Scripts/python -m app.pic.tools.neon_setup     # schema + RLS + seed + legacy data + verification
venv/Scripts/uvicorn app.main:app --port 8080
venv/Scripts/python -m app.pic.worker               # second terminal

# Web
cd frontend
cp env.example .env.local       # PIC_API_URL=http://127.0.0.1:8080
npm install && npm run dev      # open http://localhost:3000/pic
```

Or run everything in containers: `cp .env.compose.example .env`, fill it in, then `docker compose up --build`.

Sign in at `/pic/login` with organisation `AXN` and any seeded user, e.g. `buyer@axion.example`. Supplier users such as `tf.sales@axion.example` land in the supplier portal. The password is `PIC_SEED_PASSWORD`.

The migrated legacy tenants are `GMC` (Global Manufacturing Corp) and `DBY` (Dummy Buyer). Their internal users are `<role>@gmc.example` and `<role>@dby.example`, and their legacy users keep their e-mail addresses. They share the same password.

## Neon

Step-by-step instructions for Neon and GitHub, including the Actions secrets and preview branches, are in `docs/PIC_GitHub_Neon_Setup.md`. In short: put the Neon connection string in `backend/.env` as `DATABASE_URL`, using the direct (non-pooler) host and `sslmode=require`. Then run `python -m app.pic.tools.neon_setup`. It is safe to re-run. On a database that already has tenants, it adds what a newer release needs (number ranges, rule sets, templates, currencies, agents, taxonomy) without re-seeding.

## Legacy data (Docker supplier_twin)

The legacy app's data lives in the Docker Desktop container `supplier_twin_db`. To refresh the snapshot that `neon_setup` loads:

```bash
cd backend
venv/Scripts/python -m app.pic.tools.legacy_extract     # read-only; writes data/legacy/supplier_twin.json
```

`neon_setup` then does three things:
- copies all 15 legacy tables verbatim into `public`;
- migrates them into PIC tenants GMC and DBY, running the open items through the live workflows;
- writes `docs/PIC_Legacy_Migration_Report.md`, which covers reconciliation and control findings.

The legacy schema has no currency column. Use `--fx-rate` if the amounts are not INR.

## Tests

`cd backend && python -m pytest tests/pic`. This needs `TEST_DATABASE_URL`, a disposable database; the tests refuse to run against Neon. CI runs the same tests (`.github/workflows/ci.yml`), plus a frontend type check and build.

## Security model

- **Sign-in and tokens:** the API issues signed tokens. The web server keeps the token in an httpOnly cookie, so page scripts never see it.
- **Tenant isolation:** the tenant always comes from the token, and every query runs under PostgreSQL row-level security.
- **Authorisation:** scopes per role, attribute checks (cost object, plant, category, value), and segregation-of-duties rules checked at the moment of action, for people and agents alike.
- **Integrity and protection:**
  - Field-level encryption for bank accounts, GSTIN and sealed bids.
  - Append-only, hash-chained audit trail.
  - Exactly-once ERP posting with idempotency keys.
  - Throttling of failed sign-ins.
