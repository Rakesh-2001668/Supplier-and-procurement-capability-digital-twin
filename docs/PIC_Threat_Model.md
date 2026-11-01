# PIC Threat Model

Scope: the AlphaHelion Procurement Intelligence Cloud API (`backend/app/pic`), its Postgres database, the Next.js web app and BFF, the
worker, and the connections to ERP, e-sign, bank, EDI, sanctions and LLM services. Method: assets and trust boundaries first, then STRIDE
per boundary. Every mitigation names the code that implements it and the test that proves it. Residual risks and operator duties are at
the end. Status as of wave 1 (October 2026).

## 1. Assets

| # | Asset | Why it matters | Where it lives |
|---|-------|----------------|----------------|
| A1 | Money movement: invoices, payment runs, bank files, supplier bank accounts | Fraud, duplicate or diverted payment | `invoice`, `payment`, `payment_file`, `supplier_bank_account` |
| A2 | Supplier master data: GSTIN, PAN, bank, sanction status | Fake supplier, bank-change fraud | `supplier*`, field-encrypted columns |
| A3 | Commercial confidentiality: sealed bids, prices, contracts, savings | Collusion, price leakage between bidders | `bid.sealed_payload`, `contract`, `sourcing_event` |
| A4 | Identity: passwords, MFA secrets, tokens, OIDC state | Account takeover | `app_user.password_hash`, `mfa_factor.secret_enc`, JWT secret |
| A5 | Tenant isolation: one customer must never see another's rows | Breach of every other asset | row-level security, tenant in the token |
| A6 | Audit trail: hash-chained, append-only | Non-repudiation, SoD evidence | `audit_event`, `audit_event_archive` |
| A7 | Approval integrity: who approved what, under which rule version | Control bypass | `task`, `rule_set`, `sod_*`, workflow definitions |
| A8 | Encryption keys and secrets | Decryption of A2, A3, A4 | `PIC_FIELD_KEY(S)`, `PIC_JWT_SECRET`, connector credentials |
| A9 | Personal data of employees and supplier contacts (DPDP) | Legal exposure | `app_user`, notifications, audit |
| A10 | Availability of the P2P cycle (posting, payment, receiving) | Operations stop | API, worker, database |

## 2. Trust boundaries and entry points

```
 Browser ──TLS──► Next.js BFF (session cookie, CSRF same-site) ──► PIC API /v1 ──► Postgres (RLS, role pic_app)
 Supplier portal ─┘                                     │    │
 Identity provider (OIDC) ◄──────────────────────────────┘    ├──► Worker (outbox, timers, ERP retries)
 ERP / e-sign / bank / EDI / sanctions / LLM gateway ◄──── connectors (egress only, HMAC for webhooks)
```

B1 internet to BFF; B2 BFF to API (bearer token, forwarded client address); B3 API to database (tenant GUC, non-owner role, no BYPASSRLS);
B4 API to external systems (credentials from environment, never in the database); B5 tenant to tenant (same API, same tables);
B6 user to administrator functions (rules, workflow definitions, field mappings, SoD, keys); B7 agent (AI) to platform (agents act with a
role's permissions, never more).

## 3. STRIDE

Each row: threat, mitigation (code), evidence (test). IDs are stable and used in the traceability matrix.

### Spoofing

| ID | Threat | Mitigation | Evidence |
|----|--------|-----------|----------|
| S1 | Stolen or guessed password | bcrypt; sign-in throttle of 10 failures per 5 minutes per client address (`platform/http.py`); password policy of 12+ characters, three character classes, offline breached/common list and pattern check (`platform/passwords.py`, used by registration and `POST /v1/me/password`) | `test_wave1_platform.py::test_weak_and_breached_passwords_are_refused`, `::test_password_change_endpoint`, `test_production.py` throttle tests |
| S2 | Second factor missing for powerful roles | TOTP with replay protection; rule `MFA.enforce`, **on by default for every new tenant** (`seed/reference.py::create_tenant`); demo tenants stay off until flipped | `::test_new_tenants_enforce_mfa_and_demo_tenants_do_not`, `test_platform_ops.py` MFA tests |
| S3 | Forged or replayed token | HS256 JWT with issuer, expiry, per-request check that the user is still active and roles unchanged (`api/deps.py::_ensure_session_current`); challenge tokens use another issuer/audience | `test_review_platform.py` revocation tests |
| S4 | Forged webhook / punch-out / OIDC callback | HMAC verification, OIDC state + nonce + PKCE, JWKS signature check (`platform/oidc.py`) | `test_platform_ops.py` OIDC tests |
| S5 | AI agent acting as a human | Agent principals are separate (`agent_principal`), bounded by autonomy level and value limit, kill switch | `test_review_platform.py` agent tests |
| S6 | Federated sign-in with a SAML-only identity provider | Not implemented natively (the xmlsec dependency is heavy and a frequent source of vulnerabilities). Route: broker SAML to OIDC with Keycloak, see `docs/PIC_Identity_Broker.md` | documented configuration |

### Tampering

| ID | Threat | Mitigation | Evidence |
|----|--------|-----------|----------|
| T1 | Lost update / blind overwrite of a document | `row_version` optimistic locking; **ETag on every detail GET and `If-Match` on commands** (412 `STALE_WRITE`), required on document overwrites when `PIC_REQUIRE_IF_MATCH` (default in production) (`platform/preconditions.py`) | `::test_detail_gets_carry_an_etag_and_stale_if_match_is_412`, `::test_if_match_is_required_on_document_overwrites_when_enforced` |
| T2 | Retried request creates a second payment or order | **Generic Idempotency-Key on every write under /v1**: reservation, request fingerprint, 24 h replay, 422 on reuse, 409 in flight (`platform/idempotency.py`); exactly-once ERP posting keyed per message (`platform/integration.py`) | `::test_idempotent_replay_*`, `::test_concurrent_requests_with_one_key_run_once`, `test_review_f5_f6.py` posting tests |
| T3 | Audit trail altered | Append-only grants (`pic_app` has INSERT/SELECT only), SHA-256 hash chain with per-tenant advisory lock, `GET /v1/audit/verify`, verifiable archive | `test_controls.py` audit tests |
| T4 | Approval rule changed silently | Rules are effective-dated versions, never edited (P14); every version change audited; simulator compares a draft first (`api/ops.py`) | `test_production.py` rule tests |
| T5 | Workflow definition edited to bypass an approval | Definitions are versioned drafts published by `admin:workflow` only; validation refuses removing the steps the services drive, unknown roles/task kinds, unreachable steps and gateways without both outcomes; publish and retire audited; running instances keep their version (`platform/definitions.py`) | `::test_validation_finds_structural_problems`, `::test_designer_api_draft_validate_publish_and_running_instances_keep_their_version` |
| T6 | ERP field mapping used to redirect or hide data | Admin-only (`admin:integration`), versioned, validated, previewed on a sample; the canonical payload and the payload actually sent are both stored on the message; every publish audited (`platform/field_mapping.py`) | `::test_mapping_lifecycle_api_and_applied_before_the_connector` |
| T7 | SQL injection | SQLAlchemy parameter binding everywhere; the few `text()` statements take bound parameters; field names in mappings are validated paths | code review, CodeQL in `security.yml` |
| T8 | Hostile BPMN import (XXE, entity expansion) | DOCTYPE/ENTITY rejected before parsing, size limit, parsed to the same validated JSON (`platform/bpmn.py`) | `::test_bpmn_round_trip_and_viewer_xml` |
| T9 | Migration breaks the running release | Additive-only migrations checked in CI (`tools/check_migrations.py`); readiness tolerates a schema one ahead | `::test_migration_backward_compatibility_checker` |

### Repudiation

| ID | Threat | Mitigation | Evidence |
|----|--------|-----------|----------|
| R1 | "I did not approve that" | Every state change writes an audit event with actor, before/after, rule version; approvals record the acting role and any delegation | `test_signature_case.py` audit assertions |
| R2 | SoD exception denied afterwards | Request, approver's decision, validity, compensating control and every use are audited (`platform/sod.py`); admin report | `::test_sod_conflict_offers_and_honours_an_approved_time_boxed_exception` |
| R3 | ABAC denial leaves no trace because the command rolled back | Denials are audited in their own transaction (`platform/abac.py::_audit_denial`) | `::test_abac_authorize_denies_audits_and_respects_modes` |

### Information disclosure

| ID | Threat | Mitigation | Evidence |
|----|--------|-----------|----------|
| I1 | Cross-tenant read | Forced row-level security on every tenant table (`tenant_id = app.tenant_id`), tenant taken from the token only, application role without BYPASSRLS; tenant-owned workflow versions are protected by their own policy | `test_controls.py` RLS tests, `::test_designer_api_*` (other tenant sees only version 1) |
| I2 | Database dump exposes bank accounts, GSTIN, MFA secrets, sealed bids | Field-level encryption with per-tenant, per-purpose keys derived from a **versioned key ring** (key id stored with the ciphertext; rotation without downtime; `python -m app.pic.tools.reencrypt` with dry run); blind index for equality search | `::test_key_versioning_roundtrip_and_rotation`, `::test_reencrypt_job_dry_run_and_apply` |
| I3 | Bidders see each other's prices | Sealed until close, encrypted at rest, hash recorded at submission | `test_review_f3_f4.py` |
| I4 | Over-broad access inside a tenant | RBAC scopes per route + **ABAC on commands** (company code, plant, category, value limit; rule `ABAC`) | `::test_abac_*` |
| I5 | Secrets in logs or error bodies | Structured logs without bodies; validation errors drop submitted values; problem+json carries a trace id, never a stack trace | `test_production.py` |
| I6 | Personal data retained or unerasable | DPDP export/erase endpoints, retention rule, audit keeps the erasure | `test_production.py` privacy tests |
| I7 | Idempotency store holds sensitive responses | Sign-in and MFA responses are never stored; only successful JSON answers, 24 h, per user and tenant (RLS) | `idempotency.SKIP_PREFIXES` |
| I8 | LLM prompt leakage | Redaction before any gateway call; no direct vendor calls | `test_intelligence_modules.py` |

### Denial of service

| ID | Threat | Mitigation | Evidence |
|----|--------|-----------|----------|
| D1 | Request flood | Per-IP and per-user sliding-window limits, edge limits; body size limits (413) | `test_production.py` |
| D2 | One slow ERP blocks everything | Outbox + worker, back-off, dead letter, per-message isolation in savepoints | `test_review_f5_f6.py` |
| D3 | Stuck idempotency reservation after a crash | In-flight timeout (`PIC_IDEMPOTENCY_INFLIGHT_SECONDS`), then the key is reusable | `::test_in_flight_duplicate_is_409_and_expired_records_are_ignored` |
| D4 | Deadlock between the command and the denial audit | Denial audit waits at most 1.5 s for the chain lock | `abac._audit_denial` |

### Elevation of privilege

| ID | Threat | Mitigation | Evidence |
|----|--------|-----------|----------|
| E1 | Same person creates and approves | Four-eyes exclusions on approval chains; **SoD rules at command time**, blocking or (mode MITIGATE) an approved, time-boxed, use-limited exception; Critical rules are never mitigable | `::test_sod_*` |
| E2 | Self-approval of an SoD exception | The requester is excluded from the exception's approval task | `::test_sod_conflict_offers_and_honours_an_approved_time_boxed_exception` |
| E3 | Role change not effective until token expiry | Roles are re-checked against the database on every request; ABAC attributes are read from the database, not the token | `api/deps.py`, `abac._attributes` |
| E4 | Tenant admin edits shared platform definitions | Version 1 of each flow is shared and read-only for tenants (RLS: write only to rows with the caller's tenant id) | `::test_designer_api_draft_validate_publish_and_running_instances_keep_their_version` |
| E5 | Supply chain: vulnerable dependency | `pip-audit`, `npm audit`, CodeQL, secret scanning in CI | `security.yml`, `ci.yml` |

## 4. Residual risks and operator duties

1. **Key custody.** Keys live in environment variables. Production should hold them in a secret manager or Cloud KMS. Rotation procedure:
   add `<id>:<key>` first in `PIC_FIELD_KEYS`, deploy, run `python -m app.pic.tools.reencrypt --apply`, check the dry run reports `0 to rotate`,
   then remove the old key. `PIC_FIELD_KEY` (key id `v1`) must stay: it is also the blind-index key.
2. **Stateless tokens.** A token stays valid until it expires (8 h) except that a deactivated user or changed roles are refused at once.
   Shorten `PIC_JWT_TTL_MINUTES` for high-risk tenants.
3. **Rate limits are per replica** (in memory); the edge enforces the global limit.
4. **Idempotency keys and ETags are only as good as the client.** The shipped web client sends both; integrators must send a fresh key per
   logical action and reuse it only on retry.
5. **SAML** needs the identity broker in front (Keycloak); PIC itself verifies OIDC only.
6. **ABAC is permissive for users without attributes** (by design, so shipped users keep working). Give restricted users the
   `company_codes`, `plants`, `categories` or `value_limit_minor` attributes; check with the ABAC simulator (Administration, Approval simulation).
7. **Mapping and workflow editors are powerful.** Grant `admin:workflow` and `admin:integration` only to a small group, and review the audit
   events `PUBLISHED`, `RETIRED`, `RULE_CHANGED`.
8. **Penetration test and DAST** (`security.yml` ZAP baseline) cover the web surface; a manual test of the tenant boundary before each major
   release is recommended.
