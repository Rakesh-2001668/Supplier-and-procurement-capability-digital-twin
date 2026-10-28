# PIC production readiness

Status of the Purchasing Intelligence Cloud against OWASP ASVS 4.0.3 Level 2 (TD §14) and the non-functional requirements
(TD §15), as of 28 October 2026. **Status** is one of:

- **Done:** implemented and covered by code or tests (referenced).
- **Needs environment:** the code is ready, but it has to be configured or verified in staging/production infrastructure.
- **Needs decision:** a business, legal or hosting decision is required first.
- **Gap:** work remains in code (owner named).

Paths are relative to the repository root. Tests in `backend/tests/pic/test_production.py` are cited as *prod-tests*.

## 1. Open decisions (owner → decision)

| # | Decision | Why it matters | Options |
|---|---|---|---|
| D1 | **Data residency:** Neon `ap-southeast-1` (Singapore) vs India | DD-11 sets India residency as the default; DPDP s.16 allows transfer unless the destination is restricted, but customer contracts / RBI payment-data rules may require India | Neon on AWS `ap-south-1` (if on the plan); Cloud SQL/AlloyDB `asia-south1` + DR `asia-south2`; accept Singapore with contract terms (CPO + legal) |
| D2 | **Hosting:** GKE Autopilot (chosen in `deploy/`) vs Cloud Run | Worker is a long-running loop; `/v1/stream` is long-lived SSE; NetworkPolicy/PDB | GKE Autopilot regional (recommended); Cloud Run with min-instances 1 + CPU always allocated for the worker |
| D3 | **Neon plan:** history retention ≥ 7 days, logical exports, compute size | RPO 15 min / RTO 4 h need PITR and an off-provider copy; region-loss RPO needs a replica | See docs/runbooks/backup-restore-dr.md |
| D4 | **MRP performance** below NFR | 50k materials projected 2–4 h vs < 10 min | Fund the planning-service optimisation (bulk loads, indexes need a migration) |
| D5 | **Identity provider** for production (OIDC SSO vs built-in passwords) | ASVS V2 L2 password/MFA requirements are simpler with an IdP | Enterprise IdP via OIDC (code exists in `platform/oidc.py`); built-in passwords only for supplier users |
| D6 | **ZAP gating** | Report-only today | Triage baseline, then make `security.yml` → `zap` blocking |
| D7 | Retention periods per category | Defaults are proposals (8 years for statutory records) | Legal review of `services/privacy.py` CATEGORIES; configure `PRIVACY-RETENTION` per tenant |

## 2. ASVS 4.0.3 Level 2

| Area | Requirement (summary) | Status | Evidence / next step |
|---|---|---|---|
| V1 Architecture | Threat model, trust boundaries documented | Needs decision | Boundaries: browser → web BFF (token in httpOnly cookie) → internal API → Neon; write the threat model with the security lead |
| V1.14 | Segregated tiers, least-privilege network | Done (manifests) / Needs environment | `deploy/k8s/networkpolicies.yaml` (API reachable only from web + monitoring), API not exposed by the Ingress |
| V2 Authentication | Password storage with an adaptive hash | Done | bcrypt (`platform/auth.py`) |
| V2.1 | Password length/strength rules, breached-password check | Gap (owner: identity) | Strength checks exist for supplier registration (`WEAK_PASSWORD`); no breached-password check |
| V2.2 | Anti-automation on authentication | Done | 10 failed sign-ins per IP per 5 min → 429 (`platform/http.py`), plus general rate limits (*prod-tests*) |
| V2.8 | MFA (TOTP) for sensitive roles | Done | `platform/mfa.py`; admin/finance/approver roles require enrolment (`services/admin.py`) |
| V3 Sessions | Session token in httpOnly, Secure, SameSite cookie; never exposed to scripts | Done | `frontend/src/app/api/auth/session.ts` |
| V3.3 | Logout / idle timeout / revocation | Gap (owner: identity) | Stateless HS256 tokens valid for 480 min; deactivated or erased users keep a valid token until expiry; add a per-request active check or revocation list |
| V4 Access control | Server-side, deny by default, tenant isolation | Done | Scopes per role (`require(...)`), ABAC attributes, SoD at command time, PostgreSQL RLS per tenant (`db.py`, migration 0002); `test_controls.py` |
| V4.2 | Protection against IDOR / cross-tenant access | Done | RLS; supplier users limited to their documents; tests in `test_controls.py` |
| V4.3 | Admin interfaces protected (MFA, role) | Done | TENANT_ADMIN scopes `admin:*`; privacy endpoints admin-only (*prod-tests*) |
| V5 Validation | Input validation, schema-based | Done | Pydantic models on every endpoint; 422 problem+json without echoing input (*prod-tests*) |
| V5.3 | Output encoding / injection | Done | SQLAlchemy parameters only; React escaping; strict API CSP `default-src 'none'` |
| V6 Cryptography | Sensitive fields encrypted at rest with managed keys | Done / Needs environment | Fernet + HKDF per-tenant keys (`platform/crypto.py`); production requires a 32-byte `PIC_FIELD_KEY` (start-up check); move to Cloud KMS envelope (KMS key in `deploy/terraform`) |
| V6.4 | Key management and rotation | Gap (owner: platform security) | No ciphertext key version yet; rotation needs a re-encryption job (docs/runbooks/secret-rotation.md) |
| V7 Errors & logging | Generic errors, no stack traces to clients | Done | problem+json for every error, `INTERNAL_ERROR` with traceId (`platform/http.py`) |
| V7.1 | Logs exclude secrets and sensitive data | Done | JSON logs with redaction of tokens, passwords, connection-string passwords, IFSC, sensitive keys (`platform/observability.py`) |
| V7.2 | Security events logged (auth, access control failures) | Done / Needs environment | Access log per request with status, user, tenant, traceId; ship stdout to Cloud Logging with 90-day retention |
| V7.3 | Log integrity | Done | Business audit is append-only and hash-chained (`platform/audit.py`, `GET /v1/audit/verify`) |
| V8 Data protection | Personal data inventory, retention, deletion | Done / Needs decision | `services/privacy.py`: export, erasure (pseudonymise), retention report (*prod-tests*); D1, D7 |
| V8.1 | No sensitive data in caches | Done | `Cache-Control: no-store` on API responses |
| V9 Communications | TLS everywhere, HSTS | Done / Needs environment | DB `sslmode=require` enforced in production; HSTS from API (`PIC_HSTS`) and web (`next.config.ts`); TLS at GCLB with ManagedCertificate, MODERN SSL policy |
| V10 Malicious code | Dependency and secret hygiene | Done | gitleaks, CodeQL (`security.yml`), pip-audit gate with justified ignores (`.github/scripts/pip_audit_gate.py`, `backend/pip-audit-ignore.txt`), npm audit (`ci.yml`) |
| V10 (finding) | python-jose GHSA-3qf3-8w2g-rqmx (critical, no fix) | Gap (owner: platform/auth.py) | Not exploitable (HS256 pinned, symmetric key); ignore expires 2027-01-31; replace with PyJWT |
| V11 Business logic | Anti-automation, sequential steps, limits | Done | Workflow state machines, SoD, idempotency keys, value limits, rate limits |
| V12 Files | Upload size and type limits | Done | Body limit 10 MiB / uploads 25 MiB (`PIC_MAX_*`), per-endpoint limits (CSV 5 MB, OCR) |
| V13 API | Authn on every endpoint, schema, rate limits | Done | Bearer tokens; OpenAPI disabled in production (`PIC_API_DOCS`); 429 with `Retry-After` |
| V14 Configuration | Hardened build, no debug, security headers | Done | Non-root images, read-only root FS, start-up refusal of weak config (`config.py`, *prod-tests*), CSP / frame-ancestors / permissions-policy (`frontend/next.config.ts`), legacy prototype off in production |
| V14.2 | Dependency inventory / SBOM | Done | `release.yml` builds images with SBOM and provenance attestations |
| DAST | OWASP ZAP | Done (report-only) | `security.yml` → `zap` (D6) |

## 3. Non-functional requirements (TD §15)

| NFR | Target | Status | Evidence / next step |
|---|---|---|---|
| Transactional latency | P95 < 400 ms | Needs environment | k6 thresholds in `tests/load` (sign-in, worklists, PO detail, requisition create+submit, invoice match); run against staging |
| Spend cube | < 3 s | Needs environment | `tests/load/spend_overview.js` threshold p95 < 3000 ms |
| MRP scale | 50,000 materials < 10 min | **Gap** (owner: planning service) | `backend/app/pic/tools/perf_mrp.py`: 1,000 materials in 170 s on a 2-CPU workstation → 50k ≈ 2.4–4 h. Hotspots: per-order source determination (51%), per-material queries without composite indexes, ORM flushes. See docs/runbooks/mrp-run-failure.md |
| Availability | 99.9% transactional | Needs environment | 2+ API/web replicas across zones, PDBs, HPA; Neon availability per plan |
| RPO / RTO | 15 min / 4 h | Needs decision (D3) | docs/runbooks/backup-restore-dr.md |
| Observability | OTel traces web → API → services → workflow → connectors | Done (propagation) / Needs environment (export) | W3C `traceparent` accepted and returned by the API, forwarded by the web BFF, stored on outbox events, worker ticks traced; OTLP export with `PIC_OTEL_ENABLED=true` and `WITH_OTEL=true` image. Connectors can add `observability.outbound_headers()` (owner: connectors) |
| Golden signals | Per service | Done | `/metrics`: request rate, latency histogram, errors per route, in-flight, rate-limited (*prod-tests*) |
| Business SLOs | PR approval latency, touchless rate, match rate, posting success | Done | `pic_slo_*` gauges from the database (cached), per tenant |
| Pipeline health | Outbox lag, workflow open/overdue, dead letters | Done | `pic_outbox_*`, `pic_workflow_*`, `pic_integration_messages` |
| Readiness | DB, migration head, worker heartbeat, outbox | Done | `/readyz` (*prod-tests*); worker heartbeat via `pg_stat_activity` application name |
| Rate limiting | Per IP and per user | Done | Sliding-window per replica (*prod-tests*); global limit at Cloud Armor (`deploy/terraform`) |
| Runbooks | Dead letters, workflow, MRP, drift, DR, release, secrets, incidents | Done | `docs/runbooks/` |
| Data residency | India (DD-11) | Needs decision (D1) | Retention report shows the database region (`GET /v1/admin/privacy/retention`) |

## 4. Production surface

| Item | Status | Evidence |
|---|---|---|
| Prototype routers (mock data) off in production | Done | `backend/app/main.py` (`PIC_ENABLE_LEGACY_DEMO`), *prod-tests* |
| Prototype screens redirect to `/pic` in production | Done | `frontend/src/proxy.ts`, `frontend/src/lib/pic/deployment.ts` |
| "Legacy demo screens" link hidden in production | Needs integration (owner: WorkspaceShell) | Read `legacyDemoEnabled` from `@/lib/pic/deployment` |
| Approval-matrix simulation (ADM-03) | Done | `services/policy_sim.py`, `POST /v1/admin/rules/simulate`, Admin → Approval simulation (*prod-tests*) |
| CI on Python 3.14 | Done in ci.yml | `neon.yml` still pins Python 3.12, but the code needs 3.14 (`uuid.uuid7`): **neon.yml will fail** until its owner bumps `python-version` |

## 5. Environment checklist before go-live

- [ ] Secret Manager versions for `pic-database-url` (direct host, `sslmode=require`), `pic-jwt-secret` (≥ 48 random chars),
      `pic-field-key` (32 random bytes, escrowed offline), `pic-metrics-token`; GitHub `neon-production` environment secrets equal.
- [ ] `PIC_ENV=production`, `PIC_TRUSTED_PROXY_HOPS=2`, `PIC_CORS_ORIGINS` empty (BFF only).
- [ ] Neon history retention ≥ 7 days; daily logical export job; DR drill done once.
- [ ] Cloud Logging retention 90 days; alerts from docs/runbooks/README.md wired.
- [ ] k6 run against staging meets thresholds; ZAP baseline triaged.
- [ ] Decisions D1–D7 recorded.
