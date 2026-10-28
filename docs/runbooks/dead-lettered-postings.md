# Dead-lettered ERP postings

**Signal:** `pic_integration_messages{status="DEAD_LETTER"} > 0`, `pic_slo_posting_success_ratio` below target, or AP reports
invoices/POs "not in SAP". Outbox events that fail 8 times are also dead-lettered (`pic_outbox_dead_letters`).

## How posting works (platform/integration.py)

1. A business command writes an `integration_message` (PENDING) in the same transaction, keyed by
   `(tenant, target_system, idempotency_key)`.
2. The worker posts it. Before any retry it **queries the ERP by external reference**, so a lost response never causes a second
   posting. Failures back off exponentially (`RETRY`); after 8 attempts the message is `DEAD_LETTER`.
3. ADM-05 (Administration → Integration monitor) shows messages; `POST /v1/integration/messages/{id}/replay` re-queues one.

## Triage (15 minutes)

1. Scope: `GET /v1/integration/messages` (tenant admin; filter on status DEAD_LETTER) or the Integration monitor tab. Group by
   `target_system` and `message_type`; read `last_error`.
2. Is it the connector or the data?
   - Many messages, same error (timeout, 401/403, TLS, DNS): **connector problem**. Check Administration → ERP connectors →
     *Test connection*; check egress (NetworkPolicy, Cloud NAT IPs allow-listed at the ERP), credentials (`PIC_*` connector
     secrets) and the ERP's own status page.
   - One document, business error (closed period, blocked vendor, GL account): **data problem**. Fix the master data in the ERP or
     in PIC (e.g. vendor block, cost centre) before replaying.
3. Is the worker running? `/readyz` → `checks.worker`; `pic_worker_heartbeat_age_seconds`.

## Fix

- Connector outage: restore connectivity, then replay in batches of ~50 (ADM-05 *Replay*). Each replay first looks the document up
  in the ERP by external reference, so replaying a message that actually posted is safe — it is marked POSTED with the ERP number.
- Data error: correct the data, replay the single message. If the payload itself is wrong (e.g. wrong amount), do **not** edit the
  message: reverse/correct the business document in PIC (credit note, PO change), which enqueues a new message with a new key.
- Never post by hand in SAP and then replay: if you must post manually, record the ERP document number on the PIC document
  through the business process so the ledger and the ERP agree, and leave the message dead-lettered with a ticket reference.

## Verify

- `pic_integration_messages{status="DEAD_LETTER"}` back to 0; `pic_slo_posting_success_ratio` recovering.
- Spot-check three replayed documents in the ERP by external reference (one each of invoice, PO, GR if affected).
- Audit trail shows `INTEGRATION_REPLAY` then `ERP_POSTED` events, with the operator as actor of the replay.

## Prevent

- Alert on the first dead letter, not on volume. Review recurring `last_error` patterns monthly with the ERP team.
