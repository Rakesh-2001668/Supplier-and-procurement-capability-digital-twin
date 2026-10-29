# Deploying PIC on Vercel

The API and the web app run as **two Vercel projects** from this repository. The database stays on Neon, and migrations
plus datasets still run from GitHub Actions (`neon.yml`). GCP (`deploy/k8s`, `deploy/terraform`) remains the target for the
market launch; this guide is for the current Vercel deployment.

## Contents

1. [What runs where](#1-what-runs-where)
2. [Before you start](#2-before-you-start)
3. [Project 1: API (`backend`)](#3-project-1-api-backend)
4. [Project 2: web (`frontend`)](#4-project-2-web-frontend)
5. [The background worker on Vercel](#5-the-background-worker-on-vercel)
6. [Database: migrations and datasets](#6-database-migrations-and-datasets)
7. [Check the deployment](#7-check-the-deployment)
8. [Known limits on Vercel](#8-known-limits-on-vercel)

## 1. What runs where

| Part | Where | How |
|---|---|---|
| Web (Next.js 16) | Vercel project `pic-web`, root directory `frontend` | Native Next.js build; region `sin1` (`frontend/vercel.json`) |
| API (FastAPI) | Vercel project `pic-api`, root directory `backend` | Python **3.14** (`backend/.python-version`), entry point `app/main.py:app`, region `sin1`, 60 s per request (`backend/vercel.json`) |
| Worker | Inside `pic-api` | Vercel Cron calls `GET /internal/worker/tick`, and the API drains the queue after every successful write (§5) |
| Database | Neon (`ap-southeast-1`, Singapore) | Pooled host for the API, direct host for migrations |
| Migrations, datasets | GitHub Actions `neon.yml` | On every push to `main` that touches `backend/` |

The browser talks only to the web app. The web app's server side calls the API (`PIC_API_URL`), so the API needs no CORS.

## 2. Before you start

- A Vercel account and team, on the **Pro** plan if background work should run every minute (§5).
- The repository connected to Vercel (Vercel → Add New → Project → Import Git Repository).
- The **same `PIC_FIELD_KEY` and `PIC_SEED_PASSWORD`** that `neon.yml` uses (GitHub environment `neon-production`).
  Tax IDs and bank accounts on Neon are encrypted with that field key; a different key makes them unreadable.
- A **rotated Neon password** (the previous one was shared in chat). Update it in Neon, then in GitHub secrets and in Vercel.

Generate the secrets once (keep them in a password manager, never in git):

```powershell
.\backend\venv\Scripts\python.exe -c "import secrets;print('PIC_JWT_SECRET=' + secrets.token_urlsafe(48));print('CRON_SECRET=' + secrets.token_urlsafe(32));print('PIC_METRICS_TOKEN=' + secrets.token_urlsafe(32))"
```

`PIC_FIELD_KEY` is **not** regenerated: reuse the existing one.

## 3. Project 1: API (`backend`)

**Create:** Vercel → Add New → Project → import the repository →

| Setting | Value |
|---|---|
| Project name | `pic-api` |
| Root Directory | `backend` |
| Framework Preset | FastAPI (detected) / Other |
| Build and Output | defaults (Vercel installs `requirements.txt`) |

**Environment variables (Production):**

| Variable | Value | Notes |
|---|---|---|
| `DATABASE_URL` | Neon **pooled** connection string, `...-pooler...neon.tech/neondb?sslmode=require` | Tenant settings are transaction-local, so the pooler is safe |
| `PIC_ENV` | `production` | Turns on the production refusals, hides `/docs`, turns off the prototype routers |
| `PIC_JWT_SECRET` | generated, ≥ 48 characters | |
| `PIC_FIELD_KEY` | the existing key | Same as GitHub `neon-production` |
| `PIC_CORS_ORIGINS` | *(empty)* | Only the web app's server calls the API |
| `CRON_SECRET` | generated, ≥ 24 characters | Vercel Cron sends it as `Authorization: Bearer …` |
| `PIC_INLINE_WORKER` | `true` | Drain events, ERP messages and timers after each write |
| `PIC_WEB_URL` | the web app's URL, e.g. `https://pic-web.vercel.app` | Links in supplier invitations and e-mails |
| `PIC_METRICS_TOKEN` | generated (optional) | Protects `/metrics` |

Integrations stay off until their variables are set: `PIC_SMTP_*`, `PIC_EDI_GATEWAY_*`, `PIC_BANK_SFTP_*`, `PIC_IRP_*`,
`PIC_OCR_URL`, `PIC_ESIGN_*`, `PIC_SANCTIONS_*`, `PIC_OIDC_*`, `PIC_ERP_<SYSTEM>_*`. ERP connectors show `NOT_CONFIGURED` in
Admin → Connectors (SAP S/4 runs as the built-in simulator); the other integrations fall back to their internal path
(e-mail and EDI messages stay queued, contracts are signed in the platform, IRN is checked locally) and say so where used.

**Deploy**, then open `https://<pic-api-domain>/healthz` → `{"status":"ok"}` and `/readyz` → `"status": "ready"`.

## 4. Project 2: web (`frontend`)

| Setting | Value |
|---|---|
| Project name | `pic-web` |
| Root Directory | `frontend` |
| Framework Preset | Next.js (detected) |

**Environment variables (Production):**

| Variable | Value |
|---|---|
| `PIC_API_URL` | `https://<pic-api-domain>` (no trailing slash) |
| `PIC_ENV` | `production` |
| `NEXT_PUBLIC_PIC_ENV` | `production` (build time: hides the legacy-demo link) |

Deploy, then sign in at `https://<pic-web-domain>/pic/login` with a demo user (for example `buyer@axion.example`) and the
`PIC_SEED_PASSWORD`.

**Deployment Protection:** Vercel protects preview deployments by default. Keep that on; the production domain is public,
and the API only answers authenticated `/v1` calls anyway.

## 5. The background worker on Vercel

Vercel runs no long-lived processes, so the worker loop (`python -m app.pic.worker`) is replaced by two triggers that call
the same code (`worker.drain`):

| Trigger | When | Configured by |
|---|---|---|
| Inline drain | After every successful `POST/PUT/PATCH/DELETE` under `/v1`, once the response has been sent | `PIC_INLINE_WORKER=true` |
| Vercel Cron | `GET /internal/worker/tick` on a schedule | `crons` in `backend/vercel.json` + `CRON_SECRET` |

Without `CRON_SECRET` the tick endpoint answers 404. Outbox events, ERP messages and timers are claimed with
`SKIP LOCKED`, so overlapping drains never process the same item twice.

**Schedule by plan:**

| Plan | `schedule` in `backend/vercel.json` | Effect |
|---|---|---|
| Hobby | `0 3 * * *` (the committed default: daily at 03:00 UTC) | Hobby rejects more frequent crons. Events still flow after each write; **timers** (approval escalations, confirmation deadlines, certificate expiry, renewal alerts) fire at the next write or the daily run |
| Pro | `* * * * *` (every minute) | Timers fire within a minute, as with the long-running worker |

Change the schedule, commit and push; Vercel picks it up on the next deployment.

## 6. Database: migrations and datasets

Nothing changes here. A push to `main` runs `neon.yml`, which:

1. applies Alembic migrations (`pic_migrations`) over the **direct** Neon host;
2. seeds new tenants, migrates the legacy snapshot and applies every dataset pack not yet loaded (`pic.dataset_load`);
3. verifies row counts, RLS, the audit hash chain and pending events.

Deploy order for a release with a migration: let `neon.yml` finish first, then the Vercel deployment. `/readyz` returns 503
while the schema is behind the code.

## 7. Check the deployment

| Check | Expected |
|---|---|
| `GET https://<api>/healthz` | 200 `{"status":"ok"}` |
| `GET https://<api>/readyz` | 200, `checks.schema` at the current head; a "worker" warning is normal on Vercel |
| `GET https://<api>/docs` | 404 (docs off in production) |
| `GET https://<api>/internal/worker/tick` without the secret | 404 |
| Vercel → pic-api → Cron Jobs → Run | 200 with `rounds`, `events`, `timers` |
| Sign in on the web app as buyer, approver, AP clerk, supplier (`tf.sales`), admin | Worklists load; a requisition submit creates its approval task within seconds |

## 8. Known limits on Vercel

| Limit | Effect | On GCP |
|---|---|---|
| No permanent worker | Timers wait for the next write or cron run (§5) | Worker deployment, every 2 s |
| 60 s per request | Long MRP runs on large tenants and big CSV imports can time out | No limit |
| In-memory rate limits and sign-in lockout per instance | Weaker limits across instances; add Vercel Firewall rules | Cloud Armor + per-pod limits |
| `/v1/stream` ends at the function limit | The browser reconnects automatically | Long-lived connection |
| Cold starts | First request after idle is slower (seconds) | Warm pods |
| Region `sin1` + Neon Singapore | Data stays in Singapore (accepted for demo data) | `asia-south1` (India) |
