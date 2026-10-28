# Secret rotation

All production secrets live in GCP Secret Manager (`pic-database-url`, `pic-jwt-secret`, `pic-field-key`, `pic-metrics-token`)
and are synced into the Kubernetes Secret `pic-secrets` by External Secrets. neon.yml uses GitHub environment secrets with the
**same values** (`DATABASE_URL`, `PIC_JWT_SECRET`, `PIC_FIELD_KEY`, `PIC_SEED_PASSWORD`). Rotate both places together.

At start-up with `PIC_ENV=production` the API and worker refuse weak values (JWT secret < 32 chars or a placeholder, field key not
32 random bytes, `DATABASE_URL` without `sslmode=require`, metrics token < 24 chars), so a bad rotation fails the rollout instead of
running insecurely. The error names the variable, never the value.

| Secret | Schedule | Impact of rotation |
|---|---|---|
| `PIC_JWT_SECRET` | 90 days, or immediately on suspicion | All sessions end (tokens are HS256, no key ids yet): users sign in again |
| Neon role password (`DATABASE_URL`) | 90 days | Brief reconnects; no data impact |
| `PIC_METRICS_TOKEN` | 180 days | Update the Prometheus scrape secret at the same time |
| `PIC_FIELD_KEY` | Only with a re-encryption plan | **Data loss if done wrong** — see below |
| Connector credentials (`PIC_*` connector secrets, e-sign HMAC, OCR keys) | Per provider policy | Test with Administration → ERP connectors → *Test connection* |
| `PIC_SEED_PASSWORD` | After every environment build | Demo/seed users only; disable seeded users in production |

## JWT signing secret

1. Generate: `python -c "import secrets;print(secrets.token_urlsafe(48))"` (on a trusted machine; do not paste into chat/tickets).
2. `printf %s "$NEW" | gcloud secrets versions add pic-jwt-secret --data-file=-`; update the GitHub secret `PIC_JWT_SECRET`.
3. External Secrets refreshes (`refreshInterval`), or force: `kubectl -n pic annotate externalsecret pic-secrets force-sync=$(date +%s) --overwrite`.
4. `kubectl -n pic rollout restart deploy/pic-api deploy/pic-worker`. All existing tokens become invalid (401 → sign-in page).
5. Disable the old Secret Manager version after 24 h; destroy after 30 days.
Improvement (backlog): add a `kid` header and accept the previous key for one TTL (480 min) to rotate without signing everyone out.

## Neon database password

1. Neon console → Roles → reset password for the application role (or create `pic_owner_v2` and grant, then switch).
2. Build the new connection string (direct host for the worker and migrations; keep `sslmode=require`), add it as a new version of
   `pic-database-url` and update the GitHub secret `DATABASE_URL`.
3. Force-sync and restart API and worker; watch `/readyz`. Old connections are cut by Neon at reset; pods reconnect (pool pre-ping).

## PIC_FIELD_KEY (field-level encryption master key)

Per-tenant keys are derived from this master key (HKDF). Ciphertext written under key A cannot be read with key B. There is no
key-version tag on ciphertext yet, so a rotation must be a **coordinated re-encryption**:
1. Change freeze for supplier bank/tax data; take a Neon branch (backup).
2. Run a re-encryption job (to be written; owner: platform security) that, for every encrypted column, decrypts with the old key and
   encrypts with the new one in one transaction per tenant, then verifies a sample.
3. Switch `pic-field-key` to the new version, restart, verify decryption of samples, keep the old key in escrow until the next
   successful DR drill.
4. On suspected key compromise: rotate as above **and** treat encrypted data as exposed (incident-response.md, personal-data breach).
Until the re-encryption job exists, do not rotate this key except under incident command. Never let neon.yml and the cluster
use different field keys.

## After any rotation

- `GET /readyz` green, sign-in works, one supplier bank account displays masked correctly (field key), `/metrics` scrape OK.
- Record date, operator, secret version ids (not values) in the change log.
