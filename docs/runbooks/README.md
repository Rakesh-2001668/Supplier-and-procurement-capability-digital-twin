# PIC operations runbooks

Runbooks for the Purchasing Intelligence Cloud (API, worker, web, Neon PostgreSQL). Technical Document §15.1 names the
first four; the rest cover backup/DR, releases, secrets, incidents and privacy requests.

| Runbook | Use when |
|---|---|
| [dead-lettered-postings.md](dead-lettered-postings.md) | `pic_integration_messages{status="DEAD_LETTER"}` > 0, or posting success SLO burning |
| [workflow-incidents.md](workflow-incidents.md) | Overdue tasks spike, approvals stuck, outbox lag, worker heartbeat absent |
| [mrp-run-failure.md](mrp-run-failure.md) | An MRP run fails, hangs or exceeds its time budget |
| [model-drift.md](model-drift.md) | Agent acceptance rate falls, touchless/match rates move, recommendation complaints |
| [backup-restore-dr.md](backup-restore-dr.md) | Data loss or corruption, Neon region outage, DR drill (RPO 15 min, RTO 4 h) |
| [release-and-rollback.md](release-and-rollback.md) | Every release; a bad deploy; a failed migration |
| [secret-rotation.md](secret-rotation.md) | Scheduled rotation, suspected leak, staff change |
| [incident-response.md](incident-response.md) | Any Sev1/Sev2: outage, security incident, personal-data breach |
| [privacy-requests.md](privacy-requests.md) | DPDP data-principal requests: access, erasure, retention reporting |

## Signals (all from `GET /metrics`, Prometheus text, `Authorization: Bearer $PIC_METRICS_TOKEN`)

Golden signals per route: `pic_http_requests_total{method,route,status}`, `pic_http_request_duration_seconds` (histogram),
`pic_http_server_errors_total`, `pic_http_requests_in_flight`, `pic_http_rate_limited_total{scope}`, `pic_http_body_too_large_total`.

Pipeline health (per tenant, from the database, cached `PIC_METRICS_CACHE_SECONDS`, default 30 s):
`pic_outbox_pending_events`, `pic_outbox_lag_seconds`, `pic_outbox_dead_letters`, `pic_workflow_open_tasks`,
`pic_workflow_overdue_tasks`, `pic_integration_messages{status}`, `pic_worker_instances`, `pic_worker_heartbeat_age_seconds`,
`pic_schema_info{revision,expected}`, `pic_metrics_collection_up`.

Business SLOs (30-day window): `pic_slo_pr_approval_latency_seconds{quantile}`, `pic_slo_touchless_ratio`,
`pic_slo_first_pass_match_ratio`, `pic_slo_posting_success_ratio`.

Suggested alerts (tune after a month of baselines):

| Alert | Expression (PromQL sketch) | Severity |
|---|---|---|
| API error rate | `sum(rate(pic_http_server_errors_total[5m])) / sum(rate(pic_http_requests_total[5m])) > 0.01` | Sev2 |
| Transactional latency | `histogram_quantile(0.95, sum by (le) (rate(pic_http_request_duration_seconds_bucket{route!~"/v1/spend.*"}[5m]))) > 0.4` | Sev3 |
| Worker down | `max(pic_worker_heartbeat_age_seconds) > 120 or max(pic_worker_instances) == 0` | Sev2 |
| Outbox lag | `max(pic_outbox_lag_seconds) > 300` | Sev2 |
| Dead letters | `sum(pic_integration_messages{status="DEAD_LETTER"}) > 0` | Sev3 |
| Posting SLO | `min(pic_slo_posting_success_ratio) < 0.995` | Sev3 |
| Schema mismatch | `min(pic_schema_info) == 0` for 30 min | Sev3 |

Probes: `GET /healthz` (liveness, no DB), `GET /readyz` (DB, schema head, worker heartbeat, outbox backlog; JSON body explains).
Logs: one JSON object per line on stdout with `traceId`, `spanId`, `requestId`, `tenant`, `user`. Every problem response carries
the same `traceId`, so a user's error screenshot leads straight to the log lines (`traceId="<id>"`).

## Access you need on call

- Read access to the log platform and metrics, `kubectl` on namespace `pic`, Neon console (project owner or admin) for restores.
- A PIC tenant administrator account (MFA enrolled) per tenant for ADM-05 replays, task reassignment and kill switches.
- Never paste `DATABASE_URL`, `PIC_JWT_SECRET`, `PIC_FIELD_KEY` or tokens into tickets or chat.
