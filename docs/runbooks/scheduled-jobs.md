# Runbook: scheduled jobs, retention and the audit archive

## How jobs run

Jobs are registered in code (`backend/app/pic/services/job_handlers.py`, framework in `services/jobs.py`). Each organisation (tenant) has one
`scheduled_job` row per job (schedule, on/off switch, last run, next run, failures) and one `job_run` row per run (status, duration, result,
error). `worker.tick()` runs the due jobs of every organisation, so the same scheduler works from:

| Host | How the tick happens |
|---|---|
| Permanent worker (`python -m app.pic.worker`) | every `PIC_WORKER_INTERVAL_SECONDS` |
| Vercel Cron | `GET/POST /internal/worker/tick` with `Authorization: Bearer $CRON_SECRET`, configured in `backend/vercel.json` |
| Admin | `POST /v1/admin/ops/tick` (runs the caller's organisation) |

`vercel.json` schedules the tick **every minute** (`* * * * *`). Vercel's Hobby plan only allows cron jobs that run once a day: on Hobby set
the schedule back to a daily value (jobs then run at most once a day, whatever their own schedule says) or use a Pro plan or a permanent
worker. Job schedules are cron expressions in the organisation's time zone (`minute hour day-of-month month day-of-week`, or `@hourly`,
`@daily`, `@weekly`, `@monthly`); a minute-level tick gives minute-level accuracy.

Guarantees: one run of a job at a time per organisation (claim row + advisory lock; a claim older than the job's timeout is taken over and the
abandoned run is marked failed); a failure rolls back that run's writes, is recorded (status, error, consecutive failures, audit event) and does
not stop other jobs or organisations; from the third failure in a row the tenant administrators are notified. Scheduling uses the wall clock,
never the pinned business clock.

Metrics (`/metrics`): `pic_job_runs_total{job,status}`, `pic_job_duration_seconds{job}`, `pic_job_last_success_timestamp_seconds{job}`
(per process). The database is the record: `GET /v1/admin/jobs` (scope `admin:ops`) shows `overdue`, `lastStatus`, `consecutiveFailures`.

## The jobs

| Key | Default schedule | Rule | Notes |
|---|---|---|---|
| `payment-due` | daily 06:30 | `PAYMENT-RUN` `{horizonDays, autoRun, approverRole}` | proposes the run as a task for the finance controller; `autoRun=true` pays only what is due today through the normal payment run |
| `erp-reconciliation` | daily 01:30 | `ERP-TARGET` | per company code; notifies finance of differences |
| `mrp-schedule` | daily 02:00 | `MRP-SCHEDULE` `{plants, mode, overlapMinutes}` | does nothing until plants are listed; a plant with a RUNNING run is skipped |
| `scorecard-monthly` | 1st of month 03:00 | none | recomputes the previous month from receipts and invoices; idempotent; manual run accepts `{"period": "YYYY-MM"}` |
| `retention-purge` | daily 03:30 | `PRIVACY-RETENTION` | dry run until `purge.dryRun` is `false` |
| `audit-archive` | Sunday 04:00 | `PRIVACY-RETENTION` | dry run until `purge.dryRun` is `false` |
| `idempotency-purge` | hourly :15 | none | deletes `idempotency_record` older than 24 h |

Jobs with a dry-run mode (all of the above) can be tried from the admin screen (Administration > Jobs > Dry run) or
`POST /v1/admin/jobs/{key}/run {"dryRun": true}`.

## Switching the purge on

1. Review the categories: `GET /v1/admin/privacy/retention`, then run the dry runs and read the counts.
2. Create a new version of rule `PRIVACY-RETENTION` (`POST /v1/admin/rules`), for example
   `{"categories": {"notification": {"days": 180}, "outbox_event": {"days": 90}, "processed_event": {"days": 90}, "timer": {"days": 180},
   "job_run": {"days": 90}, "user_profile": {"days": 365}, "audit_actor": {"days": 2920}}, "purge": {"dryRun": false},
   "audit_archive": {"hotDays": 730}}`.
   `user_profile.days` is opt-in: users deactivated for that long are pseudonymised.
3. Statutory records (invoices, payments, POs) and the audit trail are never deleted by the purge.

## Audit archive

Audit events older than `audit_archive.hotDays` move in verified batches to `audit_event_archive` (`pic.audit_archive_range()`, a
SECURITY DEFINER function: the application role still cannot update or delete audit rows). Each batch records its checkpoint (anchor and head
hash, content digest). `GET /v1/audit/verify` and the admin screen verify the chain across the archive; the newest event is never archived.
After the statutory retention (`audit_actor.days`, default 8 years) the archived rows are dropped (`pic.audit_archive_expire()`), the batch
checkpoint stays so the chain still verifies. If verification reports a break, do not run the archive job: it refuses (`AUDIT_CHAIN_BROKEN`).

## Delegation of authority and escalation

Users delegate under Account > Delegation of authority; administrators see and revoke all delegations under Administration > Delegations.
Rule `ESCALATION` `mode`: `ADD`, `REASSIGN`, or per level (`{"2": "ADD", "default": "REASSIGN"}`, the default): level 1 reminds, level 2 adds the
manager role, level 3 and beyond reassigns the task to the manager role (the original candidates lose it, are told, and it is audited). A task
is never reassigned to a role nobody eligible holds.
Existing tenants keep their current ESCALATION rule version; without `mode` the platform default above applies, so create a new
`ESCALATION` version with an explicit `mode` if a tenant wants the previous add-only behaviour.

## AI controls

`PUT /v1/admin/ai/switch` (CPO / tenant administrator) switches every agent off for the organisation. Agents are also suspended automatically
when fewer than 70% of at least 20 recent reviewed suggestions are accepted (rule `AI-CONTROL`: `minFeedback`, `window`). Turning an agent's
kill switch off restarts its feedback window. Both are visible on the Agents page.
