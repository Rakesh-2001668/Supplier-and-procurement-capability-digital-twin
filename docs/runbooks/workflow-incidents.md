# Workflow incidents: stuck approvals, overdue tasks, outbox lag, worker down

**Signals:** `pic_workflow_overdue_tasks` rising, `pic_outbox_lag_seconds` > 300, `pic_worker_instances == 0`,
`/readyz` → `checks.worker.status` = `absent`/`stale`, users report "approved but nothing happened".

## Background

- Approvals are `task` rows (role-based, SLA timers, escalations). Task completion advances the process in the same transaction.
- Side effects (notifications, follow-on steps, ERP postings) travel through the transactional **outbox**; the **worker**
  (`python -m app.pic.worker`, one replica) relays events, fires due timers and retries ERP postings every 2 s.
- The worker heartbeat is its database session's `application_name` (`pic-worker hb=<epoch>`), visible in `pg_stat_activity`,
  plus `/tmp/pic-worker.heartbeat` for its liveness probe.

## 1. Worker down or stale

1. `kubectl -n pic get pods -l app.kubernetes.io/name=pic-worker`; `kubectl -n pic logs deploy/pic-worker --tail=200`.
2. Crash-looping on start: usually configuration (`InsecureConfiguration` lists the variables at fault) or the database
   (connection refused, password). Fix the Secret / ConfigMap, then `kubectl -n pic rollout restart deploy/pic-worker`.
3. Running but `tick failed` repeatedly: read the exception (`traceId` in the log line). A poison event is retried 8 times, then
   dead-lettered, so the queue drains on its own; a systematic failure (e.g. a missing rule set) needs a fix or a rule version.
4. Heartbeat absent but the worker is healthy: the worker must use the **direct** Neon host, not the `-pooler` host (a
   transaction-mode pooler drops session settings).
5. While the worker is down, a tenant admin can run one cycle by hand: Administration → Operations → *Run worker tick now*
   (`POST /v1/admin/ops/tick`).

Never run two workers: timers and ERP retries are not yet proven safe with concurrent workers (Deployment uses `Recreate`).

## 2. Outbox lag without a worker problem

- Lag on one tenant only: a slow consumer. Find the oldest pending events (`outbox_event` where `published_at is null`, ordered by
  `occurred_at`) and the matching log lines (`trace_id` column = `traceId`). A consumer exception increments `attempts` and keeps
  `last_error`.
- Burst after an import (planned orders, ERP batch): expected; it drains at roughly a few hundred events per tick.

## 3. Overdue / stuck approvals

1. Tasks inbox (`GET /v1/tasks` as the approver) and the process view (`GET /v1/processes/{id}`) show where the token waits.
2. Nobody can work the task: the candidate role has no active user with the right scope (cost object, plant, category), or the
   only holder is excluded by four-eyes. Fix by assigning the role/attributes (Administration → Users & roles; changes are
   audited and SoD-checked) — never by completing the task as someone else.
3. Escalations not firing: timers are fired by the worker; check (1).
4. A wrong approval chain: simulate the rule (Administration → Approval simulation, `POST /v1/admin/rules/simulate`) for the
   document's date and scope; correct it by a **new effective-dated rule version**. In-flight documents keep the version they
   started with; resubmit the document if policy requires the new route.

## Verify

`pic_workflow_overdue_tasks` falling, `pic_outbox_lag_seconds` < 60, `pic_worker_heartbeat_age_seconds` < 10, affected documents
moved to the expected state (audit trail shows the steps).
