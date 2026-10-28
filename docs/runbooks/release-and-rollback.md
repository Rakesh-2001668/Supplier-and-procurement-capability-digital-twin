# Release and rollback

## Pipeline

| Step | Where | Notes |
|---|---|---|
| Tests, type check, lint, SCA, image build | `.github/workflows/ci.yml` (every PR and main) | Must be green to merge |
| Secrets scan, CodeQL, ZAP | `.github/workflows/security.yml` | gitleaks and CodeQL blocking; ZAP report-only for now |
| Images `pic-api`, `pic-web` → GHCR, tags `<sha>` and `latest` | `.github/workflows/release.yml` (push to main) | Never deploy `latest`; pin the sha |
| Database migrations + idempotent setup on Neon | `.github/workflows/neon.yml` (push to main, environment `neon-production`) | The **only** place production migrations run |
| Deploy | `kubectl apply -k deploy/k8s` with the sha set in `kustomization.yaml` | See deploy/README.md |

## Migration rule: backward-compatible for one release

neon.yml and release.yml run on the same push, so for a while **old pods run against the new schema**. Every migration must keep
the previous release working:
- Add columns as nullable or with a server default; add tables freely; add indexes `CONCURRENTLY` where large.
- Never rename or drop a column/table in the same release that stops using it. Release N stops using it; release N+1 drops it
  ("expand, then contract").
- Never change a column's type in place; add a new column, dual-write, backfill, switch reads, drop later.
- RLS policies and grants: add, never remove, within one release.
- `/readyz` treats a database **ahead** of the code as ready (warning `schema … is ahead`) and a database **behind** as not ready,
  so new pods wait for neon.yml and old pods keep serving.

Reviewers check `pic_migrations/versions/*` against this list.

## Release steps

1. Merge to main → wait for release.yml (images) and neon.yml (database) to succeed.
2. `cd deploy/k8s && kustomize edit set image pic-api=ghcr.io/<owner>/pic-api:<sha> pic-web=ghcr.io/<owner>/pic-web:<sha>`
   (or edit `kustomization.yaml`), commit, `kubectl apply -k deploy/k8s`.
3. Watch: `kubectl -n pic rollout status deploy/pic-api deploy/pic-web deploy/pic-worker`, `/readyz`, error rate and P95 for 15 min.
4. Smoke: sign in, open the tasks inbox, open one PO, one invoice; `GET /v1/audit/verify` for one tenant.

## Rollback

- **Application only** (no migration in the release, or a backward-compatible one): `kubectl -n pic rollout undo deploy/pic-api
  deploy/pic-worker deploy/pic-web`, or re-apply the previous sha. Safe because the schema is compatible with release N-1.
- **Migration is the problem:** do not hand-edit the schema. Options in order:
  1. Roll the code back (above); leave the extra schema in place (it is backward-compatible by rule).
  2. Ship a forward fix migration through neon.yml.
  3. Data damaged by the migration: Neon branch-at-timestamp restore (backup-restore-dr.md, procedure A).
  `alembic downgrade` is not used in production: downgrades are not reviewed for data safety.
- Record the rollback in the incident log with the sha and the reason.

## Feature surface flags

- `PIC_ENABLE_LEGACY_DEMO` must stay `false` in production (prototype routers serve mock data).
- `PIC_API_DOCS` (OpenAPI/Swagger) stays `false` in production; publish the OpenAPI document from CI artifacts instead.
