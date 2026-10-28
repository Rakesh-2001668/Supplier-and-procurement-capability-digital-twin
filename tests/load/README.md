# PIC load tests (k6)

Load tests for the Purchasing Intelligence Cloud `/v1` API. They check the performance NFRs in
Technical Document §15 under a realistic peak-hour mix.

> **Run these against STAGING only.** They must never run against production or the production
> Neon database. Two of the scripts **write data** (requisitions and invoices). Every script refuses
> to start unless you confirm that the target is staging (see [Safety guard](#safety-guard)).

## Contents

```
tests/load/
  lib/config.js        env-driven configuration, user pools; runs the guard at import
  lib/guard.js         production guard (init context + setup)
  lib/http.js          JSON requests, tags, Idempotency-Key, X-Request-ID, problem+json/traceId logging
  lib/auth.js          sign-in once per pooled user in setup(), per-VU sessions, 401 re-sign-in
  lib/flows.js         the user journeys and setup() discovery of seeded documents
  lib/options.js       scenario profiles (arrival rates, VUs), standalone/smoke options
  lib/thresholds.js    NFR thresholds per request kind and per scenario
  signin.js  worklists.js  po_detail.js  requisition_create_submit.js  invoice_match.js  spend_overview.js
  all.js               all six journeys together as k6 scenarios
```

## What each script measures

| Script | Requests (per iteration) | User (seeded AXN) | NFR kind | Writes |
|---|---|---|---|---|
| `signin.js` | `POST /v1/auth/token` (valid credentials), `GET /v1/me` | `SIGNIN_EMAILS` round-robin | auth + transactional | no |
| `worklists.js` | `GET /v1/tasks`, `GET /v1/notifications/unread-count`, then cursor-paginated `GET /v1/requisitions?status=APPROVED`, `GET /v1/purchase-orders?status=RELEASED,TRANSMITTED,CONFIRMED,PARTIALLY_RECEIVED`, `GET /v1/purchase-orders`, `GET /v1/invoices?status=EXCEPTION`, `GET /v1/goods-receipts`. Each list follows `nextCursor` for up to `WORKLIST_MAX_PAGES` pages. | `buyer@axion.example` | transactional | no |
| `po_detail.js` | `GET /v1/purchase-orders/{ref}` (header, lines, validation, lineage, process, ETag) and `GET /v1/purchase-orders/{ref}/schedule` for a random PO | `buyer@axion.example` | transactional | no |
| `requisition_create_submit.js` | `POST /v1/requisitions` (Idempotency-Key), then `POST /v1/requisitions/{ref}/submit`. On 5 % of iterations the create is sent again with the same key and body, and the test expects a replay (`replayed: true`, same number). | `requester@axion.example` | transactional | **yes** |
| `invoice_match.js` | `POST /v1/invoices` (capture runs the duplicate check and the 3/4-way match inline). If the invoice is in `EXCEPTION`, it is matched again with `POST /v1/invoices/{ref}/match`. | `ap.clerk@axion.example` | transactional | **yes** |
| `spend_overview.js` | `GET /v1/spend/overview`, `GET /v1/spend/cube?dims=…` (one call per `SPEND_CUBE_DIMS` slice), `GET /v1/spend/treemap`, `GET /v1/spend/suppliers`, `GET /v1/dashboard` | `category.manager@axion.example` (`spend:read`) | spend | no |
| `all.js` | All of the above at once, each as its own scenario | all of the above | all | **yes** |

### How the scripts get their data (nothing is guessed)

- **PO numbers** come from `PO_NUMBERS`, for example `PO-77410,PO-77411`. If that is not set, `setup()`
  reads them from `GET /v1/purchase-orders`.
- **The requisition line** is the seeded material `FK-M8-50` (fastener kit, `MATERIAL`/`STOCK`, plant
  `P100`, storage location `0001`, purpose `LINE_SUPPLIES`). It is the same kind of line as seed case 5
  in `backend/app/pic/seed/operations.py`. `setup()` checks the material and plant against
  `GET /v1/reference` and uses the material's standard price as `price_est_minor`. A STOCK line needs no
  account assignment, so submit does not commit cost-centre budget, and a long run never reaches
  `BUDGET_EXCEEDED`. Quantities of 100–500 EA keep the value inside the lowest DMN-01 band. Each
  submit therefore routes to a single `COST_OBJECT_OWNER` approval task.
- **The invoice target** is a PO line with goods received but not yet invoiced. `setup()` finds it from
  `GET /v1/goods-receipts` followed by `GET /v1/purchase-orders/{ref}`. On the standard seed this is the
  FK-M8-50 fastener PO: 2,000 received, nothing invoiced, 3-way match. To pin a line, set `INVOICE_PO`
  and `INVOICE_PO_LINE`.

### Why invoice_match captures new invoices instead of re-matching a seeded one

`POST /v1/invoices/{ref}/match` only accepts an invoice in `EXCEPTION`. Each call has side effects:

- it supersedes and re-creates the invoice's exception rows,
- it logs an agent run,
- it emits an outbox event and notifies AP,
- it row-locks that one invoice.

So it is not idempotent. Many VUs re-matching one seeded invoice would mostly measure lock waits on a
single row, and they would also rewrite the demo history. Instead, every iteration captures a **new**
PORTAL invoice against the seeded PO line:

- Capture runs the duplicate check and the match synchronously, so the latency of `POST /v1/invoices`
  is the capture-plus-match cost.
- `PRICE_VARIANCE_RATIO` (default 25 %) of the invoices bill 3 % over the PO price. The DMN-03
  tolerance is 1 %, so these land in `EXCEPTION` with a `PRICE` exception. They are then matched again
  through the explicit endpoint, which only ever touches invoices the test created.
- The invoices are never approved or posted. `invoiced_qty` only moves on posting, so the PO line's
  open quantity is never used up.
- The DMN-03 fuzzy duplicate rule matches invoices from the same supplier whose gross is within ₹1
  and whose date is within 3 days. To stay clear of it, the quantity cycles through 1..open quantity
  and the invoice date steps back 8 days per cycle. Invoices from one run never look like duplicates
  of each other.
- Each run starts at a random point in that sequence. A repeated run on the same database can still
  sometimes be held as `DUPLICATE`. Watch `pic_invoice_outcome{exceptions:DUPLICATE}`, or reseed
  between runs.

## NFR mapping (Technical Document §15)

| NFR | Threshold |
|---|---|
| Transactional APIs P95 < 400 ms | `http_req_duration{kind:transactional}: p(95)<400`, plus the same threshold per scenario: `http_req_duration{scenario:<name>,kind:transactional}` |
| Sign-in (treated as transactional) | `http_req_duration{kind:auth}: p(95)<400`. Sign-in runs bcrypt (cost 10), so it is CPU-bound by design. |
| Spend cube / overview < 3 s | `http_req_duration{kind:spend}: p(95)<3000` and `http_req_duration{scenario:spend_overview,kind:spend}` |
| Error rate < 1 % | `http_req_failed: rate<0.01`, overall and per scenario |
| Functional correctness | `checks: rate>0.99`, overall and per scenario |
| Rate limits raised for the test | `pic_rate_limited: count<1`. Any 429 fails the run. |

**Gross-failure aborts.** Each threshold below stops the run early. Evaluation starts after
`ABORT_EVAL_DELAY` (default `1m`):

- `http_req_failed` above 10 %
- `checks` below 90 %
- transactional P95 above 2 s
- spend P95 above 15 s

This stops a broken staging deployment from being hammered for the whole run.

Requests made in `setup()` (health probe, sign-ins, discovery) are tagged `kind:setup`. They are
excluded from the latency NFRs.

## Safety guard

`lib/guard.js` runs in the k6 **init context**, so it stops the run before any VU starts, including
with `--no-setup`. It runs again in `setup()`. The run is refused (exit code 107, or 108 from setup) when:

- `BASE_URL` is missing or does not start with `http://` or `https://`;
- `BASE_URL` contains `neon.tech`;
- the `BASE_URL` host matches an entry in `PIC_PRODUCTION_HOSTS` (comma-separated). An entry matches
  the host exactly, `host:port` exactly, or any sub-domain. Set this in CI to your production API
  host(s), for example `PIC_PRODUCTION_HOSTS=pic.alphahelion.io,api.alphahelion.io`;
- `PIC_LOAD_CONFIRM_STAGING` is not exactly `yes`.

Setup then calls `GET /healthz` and stops if the API is not up. Setup also stops at the **first** failed
sign-in, so a wrong password costs one failed attempt.

## Staging environment

The staging API must have **its own database**, never the production Neon database:

1. Use either a dedicated **Neon branch** for staging, or a disposable Postgres (a container, for
   example). Point the *staging API's* database URL at it. `BASE_URL` here is the API URL, never a
   database URL.
2. Seed it from `backend/`:
   ```bash
   python -m app.pic.seed
   ```
   This creates tenant **AXN** and the demo users (`…@axion.example`). They all share one password:
   `PIC_SEED_PASSWORD` if set, otherwise a generated one that is printed once. That shared password is
   the `PASSWORD` for these tests.
3. Raise the rate limits on the staging API (next section).
4. After runs that write data, reseed or throw away the database. See [Data written](#data-written).

## Rate limits

The API rate-limits requests per client IP and per user, per replica:

| Setting | Default |
|---|---|
| `PIC_RATE_LIMIT_PER_IP` | 600 requests per window |
| `PIC_RATE_LIMIT_PER_USER` | 1,200 requests per window |
| `PIC_RATE_LIMIT_WINDOW_SECONDS` | 60 |

Over the limit, the API returns 429 with `Retry-After`.

`all.js` at `LOAD_FACTOR=1` sends about **3,300 requests per minute** from one load generator, and most
of them are as one buyer. With the defaults it would be throttled almost at once. Before a test, do
**one** of the following on the **staging API** (never production):

- **Raise the limits.** Set, for example, `PIC_RATE_LIMIT_PER_IP=100000` and
  `PIC_RATE_LIMIT_PER_USER=100000` in the staging API's environment, then restart or redeploy it.
- **Spread the load.** Create several test users per role on staging and pass them as pools:
  `BUYER_EMAILS=a@…,b@…,c@…` (also `REQUESTER_EMAILS`, `AP_EMAILS`, `SPEND_EMAILS`, `SIGNIN_EMAILS`).
  VU *n* uses user *(n-1) mod pool size*. This only spreads the per-user limit. The per-IP limit still
  applies to the load generator, so raise that one, or run k6 from several hosts.

`setup()` prints a warning when the planned rate exceeds 80 % of the per-IP limit. If you have already
raised the limit, tell k6 the staging value (for example `-e PIC_RATE_LIMIT_PER_IP=100000`) and the
warning goes away. Any 429 that still happens fails the `pic_rate_limited` threshold.

**Sign-in brute-force limit.** `POST /v1/auth/token` blocks a client IP for 5 minutes after **10 failed**
sign-ins. A successful sign-in clears the count. So:

- Every script signs in once per pooled user in `setup()` and shares the tokens with all VUs. VUs never
  sign in per iteration.
- If a token expires during a long soak (default TTL 480 min), the VU signs in again once, with valid
  credentials.
- Only `signin.js` (and the `signin` scenario in `all.js`) signs in per iteration, and only with valid
  credentials.
- The throttle keys on the first `X-Forwarded-For` hop. Behind a load balancer, all traffic from one
  k6 host is one IP.

## Users

The defaults are seeded AXN users. Override them with single values (`BUYER_EMAIL`, …) or pools
(`BUYER_EMAILS`, …):

| Pool | Default | Needs |
|---|---|---|
| buyer | `buyer@axion.example` | `pic:read`, `tasks:work` |
| requester | `requester@axion.example` | `req:create` (only the requester can submit their own requisition) |
| ap | `ap.clerk@axion.example` | `invoice:capture`, `invoice:resolve` |
| spend | `category.manager@axion.example` | `spend:read` |
| signin | `buyer@`, `requester@`, `buyer.lead@axion.example` | any |

The seeded MFA policy lists `AP_CLERK` among the roles that need MFA, but it is not enforced
(`enforce: false`). If staging enforces MFA, or a test user has an authenticator, sign-in returns
`mfaRequired` or `MFA_ENROLMENT_REQUIRED` and setup stops with a clear message. Use load-test users
without MFA in that case.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `BASE_URL` | — (required) | Staging API root, e.g. `https://pic-staging.example.com` (no `/v1`) |
| `PIC_LOAD_CONFIRM_STAGING` | — (required) | Must be `yes` |
| `PIC_PRODUCTION_HOSTS` | — | Comma-separated production hosts to refuse |
| `PASSWORD` | — (required) | Shared password of the seeded users on staging. Never logged. |
| `TENANT` | `AXN` | Tenant code |
| `BUYER_EMAIL(S)`, `REQUESTER_EMAIL(S)`, `AP_EMAIL(S)`, `SPEND_EMAIL(S)`, `SIGNIN_EMAILS` | see [Users](#users) | User pools |
| `SMOKE` | — | `1` runs 1 VU × 1 iteration per scenario |
| `RATE_PER_MIN` | per script | Standalone scripts: target iterations per minute |
| `LOAD_FACTOR` | `1` | `all.js`: multiplies every scenario's rate and VU allocation |
| `DURATION` / `RAMP_UP` / `RAMP_DOWN` | `5m` / `2m` / `1m` | Hold, ramp-up and ramp-down times |
| `VUS` / `MAX_VUS` | per profile | Override preallocated and maximum VUs |
| `THINK_TIME_MAX` | `1.0` | Random pause between user steps, in seconds (`0` turns it off) |
| `REQUEST_TIMEOUT` | `30s` | Per-request timeout |
| `ABORT_EVAL_DELAY` | `1m` | Grace period before gross-failure aborts are evaluated |
| `MAX_ERROR_LOGS_PER_VU` | `20` | Maximum number of failure log lines per VU |
| `WORKLIST_PAGE_SIZE` / `WORKLIST_MAX_PAGES` | `50` / `2` | Worklist pagination |
| `PO_NUMBERS` | discovered | e.g. `PO-77410,PO-77411` |
| `REQ_MATERIAL` / `REQ_PLANT` / `REQ_STORAGE_LOCATION` / `REQ_PURPOSE_CODE` | `FK-M8-50` / `P100` / `0001` / `LINE_SUPPLIES` | Requisition line |
| `IDEMPOTENCY_REPLAY_RATIO` | `0.05` | Share of requisition creates that are re-sent with the same Idempotency-Key |
| `INVOICE_PO` / `INVOICE_PO_LINE` | discovered | PO and line to invoice against |
| `INVOICE_DATE_BASE` | today (UTC) | Latest invoice date (YYYY-MM-DD) |
| `PRICE_VARIANCE_RATIO` | `0.25` | Share of invoices billed above tolerance, then re-matched |
| `SPEND_CUBE_DIMS` | `category;supplier,period;plant,material_group` | Cube slices: `;` between calls, `,` between dimensions |
| `PIC_RATE_LIMIT_PER_IP` / `_PER_USER` / `_WINDOW_SECONDS` | `600` / `1200` / `60` | The staging values, for the pre-flight warning only |

## Running

Always run a smoke test first: one iteration of each journey.

```bash
cd tests/load
export BASE_URL=https://pic-staging.example.com PIC_LOAD_CONFIRM_STAGING=yes
export PIC_PRODUCTION_HOSTS=pic.alphahelion.io     # your production API host(s)
read -rs PASSWORD && export PASSWORD               # type it; it does not go into shell history

k6 run -e SMOKE=1 worklists.js                     # read-only
k6 run -e SMOKE=1 all.js                           # writes 1 requisition + 1 invoice
```

Then run the real test:

```bash
k6 run worklists.js                                # 300 it/min, 2 m ramp + 5 m hold + 1 m ramp-down
k6 run -e RATE_PER_MIN=120 -e DURATION=10m po_detail.js
k6 run -e LOAD_FACTOR=1 -e DURATION=15m all.js     # peak-hour mix
k6 run -e LOAD_FACTOR=2 -e DURATION=30m all.js     # 2x peak (stress)
```

k6 reads `__ENV` from both `-e NAME=value` and the process environment, so exported variables work as
shown. Pinned and tested version: **k6 v2.3.0**.

### Docker

The scripts import `./lib/*.js`, so `docker run … k6 run - < all.js` does **not** work: a script piped
on stdin cannot resolve relative imports. Mount the directory instead. Pass secrets as container
environment variables (`-e PASSWORD` with no value copies it from your shell), not as k6 `-e`
arguments.

```bash
docker run --rm -i \
  -e BASE_URL -e PIC_LOAD_CONFIRM_STAGING -e PIC_PRODUCTION_HOSTS -e PASSWORD \
  -e LOAD_FACTOR=1 -e DURATION=15m \
  -v "$PWD/tests/load:/scripts:ro" -v "$PWD/k6-results:/results" \
  grafana/k6:2.3.0 run --summary-export=/results/summary.json --out json=/results/metrics.json.gz /scripts/all.js
```

- **Git Bash on Windows:** prefix the command with `MSYS_NO_PATHCONV=1`, or Git Bash rewrites
  `/scripts` into a Windows path.
- **API on the Docker host:** use `BASE_URL=http://host.docker.internal:8080`.
- **`k6 archive`:** avoid it for this suite. An archive freezes the `-e` values given at archive time,
  secrets included.

Validate the scripts without contacting any server. `inspect` evaluates the init context, so the guard
variables are needed:

```bash
for f in signin worklists po_detail requisition_create_submit invoice_match spend_overview all; do
  MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD/tests/load:/scripts:ro" \
    -e BASE_URL=https://pic-staging.example.com -e PIC_LOAD_CONFIRM_STAGING=yes \
    grafana/k6:2.3.0 inspect /scripts/$f.js > /dev/null && echo "$f ok"
done
```

## Data written

Each run leaves the following on staging. Plan to reseed or discard the staging database afterwards.

- **requisition_create_submit:** one `IN_APPROVAL` requisition (`purpose_text` starts with
  `k6 load test <runId>`) per iteration. Each opens a `COST_OBJECT_OWNER` approval task for
  `plant.controller@axion.example`, and adds audit events, process history and idempotency records.
- **invoice_match:** one unposted invoice per iteration. Supplier invoice numbers are
  `LT<runId>-<vu>-<iter>`; most are `MATCHED`, about 25 % are `EXCEPTION`/`PRICE`. Each adds
  exception rows, AP notifications, outbox events and a PO→invoice lineage link.

These side effects change what you measure:

- The invoiced PO's lineage grows with every invoice, so `GET /v1/purchase-orders/{ref}` for that one
  PO gets heavier over a long run. This is real behaviour, but keep it in mind when you compare runs.
- The worklists grow as data accumulates, so worklist results depend on how much earlier runs wrote.
- Document numbers come from a per-tenant number-range row (`UPDATE … RETURNING`). Requisition creates
  in one tenant are therefore serialised on that row, so contention there is real.

## Reading the results

- **End-of-test summary.** Each threshold shows ✓ or ✗ with its value. Look first at:
  - `http_req_duration{kind:…}`;
  - the per-scenario `http_req_duration{scenario:…,kind:…}`;
  - `http_req_failed`, `checks`, `pic_rate_limited`;
  - `dropped_iterations`. If this is above zero, k6 ran out of VUs (`MAX_VUS`) for the arrival rate,
    which means the API is too slow or `MAX_VUS` is too low.
- **Exit codes:**

  | Code | Meaning |
  |---|---|
  | `0` | All thresholds passed |
  | `99` | One or more thresholds failed |
  | `107` | Script error (this includes the guard refusing in init) |
  | `108` | Aborted by `exec.test.abort` in setup (guard, health check, sign-in, discovery) |

  An `abortOnFail` threshold also ends the run early, with `99`.
- **Failures** are logged with the API's problem `code` and `traceId`. Each request sends an
  `X-Request-ID: k6-<uuid>` header, and the API uses it as the `traceId`, so you can search the API's
  structured access log for the same id. For example:
  `[worklists vu=3 iter=41] GET /v1/invoices -> 503 code=<problem code> traceId=k6-… <detail>`
- **Custom metrics:**

  | Metric | Tags |
  |---|---|
  | `pic_problem_responses` | `code`, `name` |
  | `pic_rate_limited` | — |
  | `pic_invoice_outcome` | `status`, `variance`, `exceptions` |
  | `pic_requisitions_submitted` | `status` |

- **Export:**
  - `--summary-export=summary.json` writes the end-of-test summary as JSON.
  - `--out json=metrics.json.gz` writes every sample (gzipped NDJSON) for later analysis.
  - `K6_WEB_DASHBOARD=true K6_WEB_DASHBOARD_EXPORT=report.html k6 run …` writes a standalone HTML
    report.
- **Request names.** Requests are tagged by templated name (`name` tag, e.g.
  `GET /v1/purchase-orders/{ref}`), so per-endpoint stats stay readable. Filter on
  `metric=="http_req_duration" && data.tags.name==…` in the JSON output.

## Suggested CI job (manual, staging only)

This is not committed as a workflow. Copy it to `.github/workflows/load-staging.yml` once it has been
reviewed. It assumes a GitHub **environment** `staging` holding these secrets:

- `PIC_STAGING_BASE_URL`
- `PIC_STAGING_PASSWORD`
- `PIC_PRODUCTION_HOSTS`

Protect that environment with required reviewers.

```yaml
name: load-test-staging
on:
  workflow_dispatch:
    inputs:
      script:
        description: Script in tests/load
        type: choice
        options: [all.js, worklists.js, po_detail.js, spend_overview.js, signin.js, requisition_create_submit.js, invoice_match.js]
        default: all.js
      load_factor:
        description: LOAD_FACTOR (all.js)
        default: "1"
      duration:
        description: Hold duration
        default: 10m
      smoke:
        description: Smoke only (1 iteration)
        type: boolean
        default: true
concurrency: { group: load-test-staging, cancel-in-progress: false }
jobs:
  k6:
    runs-on: ubuntu-latest
    environment: staging            # secrets + required reviewers live here
    timeout-minutes: 90
    steps:
      - uses: actions/checkout@v4
      - name: Run k6 against staging
        env:
          BASE_URL: ${{ secrets.PIC_STAGING_BASE_URL }}
          PASSWORD: ${{ secrets.PIC_STAGING_PASSWORD }}
          PIC_PRODUCTION_HOSTS: ${{ secrets.PIC_PRODUCTION_HOSTS }}
          PIC_LOAD_CONFIRM_STAGING: "yes"
          LOAD_FACTOR: ${{ inputs.load_factor }}
          DURATION: ${{ inputs.duration }}
          SMOKE: ${{ inputs.smoke && '1' || '' }}
        run: |
          mkdir -p k6-results
          docker run --rm \
            -e BASE_URL -e PASSWORD -e PIC_PRODUCTION_HOSTS -e PIC_LOAD_CONFIRM_STAGING \
            -e LOAD_FACTOR -e DURATION -e SMOKE \
            -v "$PWD/tests/load:/scripts:ro" -v "$PWD/k6-results:/results" \
            grafana/k6:2.3.0 run \
              --summary-export=/results/summary.json --out json=/results/metrics.json.gz \
              /scripts/${{ inputs.script }}
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: k6-${{ inputs.script }}-${{ github.run_id }}
          path: k6-results/
```

Before the first non-smoke run, raise the staging API's rate limits (see [Rate limits](#rate-limits)).
After write runs, reseed the staging database.
