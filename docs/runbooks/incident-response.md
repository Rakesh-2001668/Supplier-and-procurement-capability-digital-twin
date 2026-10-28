# Incident response

## Severity

| Sev | Definition | Response |
|---|---|---|
| 1 | Production down for all tenants; data loss/corruption; confirmed security breach or personal-data breach | Page on-call + incident commander now; status page; executive notice within 1 h |
| 2 | Major function down (approvals, invoice posting, ERP integration) or one tenant down; suspected breach | Page on-call; update every 30 min |
| 3 | Degraded (latency above NFR, dead letters, a failing agent) with a workaround | Next business hours |

## Roles

Incident commander (decides, communicates), operations lead (hands on keyboard), scribe (timeline in the incident doc),
communications (customers, regulators). One person may hold several roles in a small team; the IC never debugs.

## First 30 minutes

1. Open an incident doc and channel; note start time (IST and UTC).
2. Stabilise: roll back a recent release (release-and-rollback.md), scale out, kill-switch a misbehaving agent (model-drift.md),
   or freeze writes (scale API/worker to 0) if data is being damaged.
3. Collect evidence before changing things: `traceId`s from user reports, log queries by `traceId`/`tenant`, `/readyz` body,
   metric screenshots, `GET /v1/audit/verify` per tenant.
4. Communicate: who is affected, what works, next update time.

## Security incident specifics

- Suspected token or secret leak: rotate (secret-rotation.md) — JWT secret rotation ends every session immediately.
- Suspected account takeover: deactivate the user (Administration → Users & roles → inactive; audited), review the audit trail
  for the actor `u:<email>`; if the user approves payments or bank changes, review SoD violations and recent bank-detail changes
  (two-approver rule) and payment runs.
- Preserve evidence: do not delete logs or branches; export the relevant audit range; take a Neon branch for forensics.
- Audit chain broken (`/v1/audit/verify` returns `valid: false`): Sev1. Note `broken_at_seq`; compare with a pre-incident branch.

## Personal-data breach (DPDP Act 2023)

A breach of personal data (e.g. supplier bank details, employee contact data) must be reported to the **Data Protection Board of
India and each affected data principal** (s.8(6)), in the form and time the DPDP Rules prescribe — legal counsel owns the
notification; operations supplies facts: what data, which tenants and principals, when, how contained. Customers (tenants) are
data fiduciaries for their users' data; notify them without delay so they can meet their duties. Start the clock at awareness.

## Closing

Post-incident review within 5 business days: timeline, root cause, what detection missed, actions with owners and dates.
Blameless. Update the relevant runbook.
