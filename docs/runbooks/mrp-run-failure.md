# MRP run failure or slowness

**Signals:** `POST /v1/mrp/runs` returns 5xx or times out, a run stays incomplete, planners report missing planned orders, or the
run exceeds its time budget (NFR: regenerative run for 50,000 materials < 10 minutes).

## Known limitation (October 2026)

The scale harness (`backend/app/pic/tools/perf_mrp.py`) measured about 170 s for 1,000 materials on a 2-CPU workstation
(≈ 32 SQL statements per material; source determination per planned order dominates). Extrapolated, 50,000 materials take
2–4 hours: **the NFR is not met yet**. Until the planning service is optimised (bulk loads per plant, composite indexes on
`(tenant_id, material_id, plant)`, cached source determination, bulk inserts), run regenerative MRP for large plants out of
hours and prefer net-change runs.

Measure on staging (never on production Neon):

```bash
cd backend
export DATABASE_URL=postgresql://postgres@127.0.0.1:54329/pic_perf_mrp PIC_JWT_SECRET=perf PIC_FIELD_KEY=perf
python -m app.pic.tools.perf_mrp --database-url "$DATABASE_URL" --materials 10000 --reset --profile
```

The harness refuses any `neon.tech` URL and any database holding real tenants.

## Triage

1. Find the run: `GET /v1/mrp/runs` → `GET /v1/mrp/runs/{ref}` (status, counts) and `.../exceptions`.
2. API logs for the run's request (`traceId` from the client's error, or `route="/v1/mrp/runs"`): a timeout at the ingress
   (3600 s on the BackendConfig) or the web BFF shows up as 502/504 while the API keeps working.
3. Database: long transaction? (Neon console → Monitoring → active queries). An MRP run is one transaction; if it was killed,
   nothing was written (no partial planned orders) — re-running is safe.
4. Data errors (exceptions such as missing source of supply, missing calendar): these are business exceptions, not failures; route
   them to the MRP controller.

## Recover

- Failed/killed run: fix the cause (data, timeout), re-run with the same mode. Planned orders of the previous run are replaced by
  a regenerative run; firmed orders are kept.
- Timeout only: run from a machine inside the cluster network against the API service directly (bypass the browser), or split by
  plant.
- If the database is under pressure from a run during business hours, cancel the query from the Neon console (the transaction rolls
  back) and reschedule.

## Verify

Run status complete, planned orders and exceptions as expected for a sample of materials, workflow step recorded in the audit trail.
