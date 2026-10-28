# Backup, restore and disaster recovery

**Targets (TD §15):** RPO 15 minutes, RTO 4 hours for the transactional database.

## What protects the data

| Layer | Mechanism | Covers |
|---|---|---|
| Neon point-in-time restore (PITR) | Write-ahead log retained for the project's *history retention* window | Any moment within the window: bad migration, bad bulk update, accidental delete |
| Neon branches | Instant copy-on-write branch at a timestamp/LSN | Inspect-before-restore; restore a single table by copying from a branch |
| Logical export | `pg_dump` of schema `pic` to encrypted object storage, daily | Neon project loss, account compromise, long-term retention beyond PITR |
| Application integrity | Append-only hash-chained audit (`GET /v1/audit/verify`) | Detects tampering or partial restores of audit data |
| Secrets | Secret Manager (versioned) + offline escrow of `PIC_FIELD_KEY` | Encrypted columns are unreadable without the field key |

**Decisions needed (hosting):**
1. Set Neon history retention to **at least 7 days** on the production project (plan-dependent; the free tier is too short for
   RPO/RTO commitments). PITR gives an RPO of seconds within that window, comfortably inside 15 minutes.
2. Daily logical export job (GitHub Actions scheduled workflow or a Kubernetes CronJob) to a bucket in the residency region,
   with object lock / retention, encrypted with a key that is **not** in the same account as Neon.
3. Region: Neon `ap-southeast-1` (Singapore) today. DD-11 asks for India primary (asia-south1) and DR in asia-south2; see the
   residency decision in docs/PIC_Production_Readiness.md. Neon has no cross-region replica: regional DR means restoring the
   latest logical export (RPO = export age, up to 24 h) unless a continuous replica (logical replication to a second provider)
   is set up — required to meet RPO 15 min for a **region** loss.

## Restore procedures

### A. Undo a bad change (most common): branch, verify, then restore

1. Note the time just before the incident (audit trail `ts`, deploy time, or the log line). Freeze writes if the damage is
   spreading: scale the API and worker to 0 (`kubectl -n pic scale deploy/pic-api deploy/pic-worker --replicas=0`) — the web
   shows "API unavailable".
2. Neon console → Branches → *Create branch* from production **at that timestamp** (name `restore-<date>`).
3. Verify the branch: connect with a read-only role, run `SELECT version_num FROM pic.alembic_version`, row counts for the affected
   tables, and `GET /v1/audit/verify` through a staging API pointed at the branch.
4. Choose:
   - **Whole database:** Neon *Restore* the production branch to the timestamp (Neon keeps a backup branch of the pre-restore
     state). Connection strings stay the same.
   - **Single table / tenant:** copy rows from the restore branch (`pg_dump -t pic.<table> --data-only` with a `WHERE tenant_id`
     filter via `COPY (SELECT …)`) into production inside a transaction, as the owner role. Re-verify the audit chain afterwards.
5. Scale API (2) and worker (1) back up; check `/readyz`, `pic_outbox_lag_seconds` (the outbox replays unpublished events; consumers
   are idempotent via `processed_event`) and ERP postings (query-before-retry prevents double posting).
6. ERP reconciliation: documents posted to SAP after the restore point now exist only in SAP. Run the reconciliation
   (`reconciliation_run`) and re-create or link those documents before reopening.

### B. Lost Neon project or region (DR)

1. Declare Sev1 (incident-response.md). Create a new Neon project (or Cloud SQL instance in the DR region).
2. Restore the latest logical export: `psql` the schema dump, then the data; run `python -m alembic -c alembic_pic.ini upgrade head`
   from a release-tagged checkout to reach this release's head; run the RLS/role setup only through the reviewed setup tooling.
3. Update the `pic-database-url` secret (new Secret Manager version), restart API and worker.
4. RTO budget: 30 min decision + 60–120 min restore (size-dependent) + 60 min verification/ERP reconciliation ≈ under 4 h. Rehearse
   twice a year and record the timings here.

## Key custody: PIC_FIELD_KEY

Bank accounts, tax ids and sealed bids are encrypted with per-tenant keys derived (HKDF) from `PIC_FIELD_KEY`. **A restored
database is useless without the key that was active when the rows were written.**
- Store the key in Secret Manager (versioned, region-pinned) **and** in an offline escrow: two sealed copies held by two named
  officers (e.g. CFO delegate and CISO), checked yearly.
- Never rotate it without re-encrypting (secret-rotation.md). Backups must record which key version they need.
- Losing the key = losing all encrypted fields (suppliers must re-submit bank details).

## Drill checklist (quarterly)

- [ ] Branch-at-timestamp restore of production into `restore-drill`, verify counts and audit chain, delete the branch.
- [ ] Restore the latest logical export into a scratch project; time it.
- [ ] Decrypt one supplier bank account on the scratch restore with the escrowed field key (proves key custody).
- [ ] Record RPO/RTO achieved and gaps.
