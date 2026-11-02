# PIC Event Catalogue

Every event the platform emits through the transactional outbox (`outbox.emit`), with its producers, its consumers and the JSON Schema of its payload. Generated from the code by `python -m app.pic.events.catalogue write`; the schema files are in `backend/app/pic/events/schemas/<topic>.json` and every real event payload is validated against them in `backend/tests/pic/test_wave1_jobs.py`.

Envelope of every event (also what an external bus receives): `eventId`, `tenantId`, `type` (the topic), `occurredAt`, `actor`, `objectRef {type, id, ref}`, `version` (payload schema version, currently 1), `traceId`, `data` (the payload below).

Delivery: at least once, in order per tenant; consumers are idempotent (`processed_event`); a failing consumer is retried with back-off and the event is dead-lettered after 8 attempts (`outbox_event.last_error`).

| Event | Object | Producers | Consumers | Payload (required keys) |
|---|---|---|---|---|
| `accessorial.claimed` | ACCESSORIAL_CHARGE | `services/ind_logistics.py:152` | stream only | `po`, `status`, `amountMinor` |
| `advance.approved` | ADVANCE_PAYMENT | `services/ind_construction.py:293` | stream only | `po`, `grossMinor`, `document` |
| `agent.recommendation.created` | RECOMMENDATION | `services/notifications.py:_recommendation_events` | `notify-recommendation` | `agent`, `title`, `candidateRole`, `objectType`, `objectId`, `objectRef` |
| `agent.suspended` | AGENT | `platform/agents.py:145` | `notify-agent-suspended` | `agent`, `reason`, `acceptance`, `events`, `automatic` |
| `ai.switch.changed` | TENANT_AI | `platform/agents.py:99` | `notify-ai-switch` | `enabled`, `reason` |
| `asn.received` | ASN | `services/receiving.py:159` | `notify-asn-received` | `po`, `expected` |
| `cold_chain.excursion` | COLD_CHAIN_READING | `services/ind_healthcare.py:126` | stream only | `material`, `object`, `minutes`, `minSeen`, `maxSeen` |
| `cold_chain.rejected` | COLD_CHAIN_READING | `services/ind_healthcare.py:239` | stream only | `material`, `valueMinor` |
| `consignment.withdrawn` | MATERIAL | `services/receiving.py:825` | `par-level-replenishment` | `material`, `plant`, `qty`, `purpose`, `usageRef`, `costObject`, `liabilityMinor`, `lots` |
| `contract.activated` | CONTRACT | `services/contract.py:652` | `savings-contracted` | `supplierId`, `sourceEventId`, `validFrom`, `validTo` |
| `contract.amended` | CONTRACT | `services/amendments.py:445` | `notify-contract-amended` | (see schema) |
| `contract.consumption.threshold` | CONTRACT | `services/contract.py:746` | `notify-contract-consumption` | `threshold`, `consumedPct`, `line`, `description`, `releasedQty`, `targetQty`, `ownerId` |
| `contract.terminated` | CONTRACT | `services/amendments.py:442` | `notify-contract-terminated` | `forCause`, `openPurchaseOrders` |
| `debit_note.posted` | DEBIT_NOTE | `services/debit_notes.py:388` | stream only | `invoice`, `erpDocument`, `grossMinor` |
| `debit_note.received` | DEBIT_NOTE | `services/debit_notes.py:199` | stream only | `invoice`, `supplier`, `grossMinor` |
| `debit_note.rejected` | DEBIT_NOTE | `services/debit_notes.py:274` | stream only | `invoice`, `reason` |
| `delegation.created` | DELEGATION | `services/delegation.py:120` | `notify-delegation-created` | `delegationId`, `delegatorId`, `delegateId`, `validFrom`, `validTo`, `roles`, `valueLimitMinor`, `createdByAdmin` |
| `delegation.revoked` | DELEGATION | `services/delegation.py:156` | `notify-delegation-revoked` | `delegationId`, `delegatorId`, `delegateId`, `revokedBy`, `reason` |
| `erp.sync.finished` | ERP_SYNC | `services/erp_sync.py:445` | stream only | `kind`, `status`, `counts` |
| `finance.period.closed` | POSTING_PERIOD | `services/finance_controls.py:372` | stream only | `companyCode`, `period`, `unpostedInvoices`, `grirAccrualMinor` |
| `finance.period.reopened` | POSTING_PERIOD | `services/finance_controls.py:414` | stream only | `companyCode`, `period`, `reason` |
| `goods_receipt.posted` | GOODS_RECEIPT | `services/receiving.py:330` | `kanban-refill`, `supplier-scorecard` | `grId`, `po`, `qualityHold`, `lines` |
| `goods_receipt.reversed` | GOODS_RECEIPT | `services/receiving.py:524` | `supplier-scorecard` | `grId`, `po`, `from`, `reason` |
| `guarantee.expired` | BANK_GUARANTEE | `services/ind_construction.py:196` | stream only | `po`, `expiry` |
| `guarantee.expiring` | BANK_GUARANTEE | `services/ind_construction.py:184` | stream only | `po`, `daysLeft`, `expiry` |
| `guarantee.verified` | BANK_GUARANTEE | `services/ind_construction.py:102` | stream only | `po`, `kind`, `expiry` |
| `index.updated` | INDEX | `services/ind_logistics.py:255` | stream only | `index`, `inserted`, `revised` |
| `integration.batch.imported` | INTEGRATION_BATCH | `services/erp_import.py:227` | `notify-batch-imported` | `sourceSystem`, `kind`, `batchRef`, `accepted`, `rejected`, `mrpRuns` |
| `invoice.captured` | INVOICE | `services/ind_manufacturing.py:126`, `services/payables.py:259`, `services/payables.py:1467` | `notify-invoice-captured` | `supplier`, `grossMinor`, `channel` |
| `invoice.disputed` | INVOICE | `services/payables.py:662` | `notify-invoice-disputed` | `exception`, `delta`, `note` |
| `invoice.early_payment.accepted` | INVOICE | `services/early_payment.py:180` | stream only | `offer`, `discountMinor`, `payOn` |
| `invoice.early_payment.offered` | INVOICE | `services/early_payment.py:164` | stream only | `offer`, `source`, `discountMinor`, `payOn` |
| `invoice.exception.raised` | INVOICE | `services/payables.py:506` | `notify-invoice-exception` | `exceptions` |
| `invoice.paid_in_erp` | INVOICE | `services/erp_sync.py:381` | stream only | `erpDocument`, `clearingDocument`, `clearingDate` |
| `invoice.posted` | INVOICE | `services/payables.py:937` | `rebate-accrual`, `savings-realised`, `spend-cube`, `supplier-scorecard` | `invoiceId`, `erpDocument`, `supplier`, `grossMinor` |
| `invoice.scf.elected` | INVOICE | `services/early_payment.py:268` | stream only | `offer`, `maturity`, `grossMinor` |
| `kanban.signalled` | KANBAN_CARD | `services/ind_manufacturing.py:202` | `kanban-replenishment` | `material`, `plant`, `binQty` |
| `licence.unused_flagged` | LICENCE | `services/ind_it.py:130` | stream only | `utilisationPct`, `unusedQty`, `potentialSavingMinor`, `termEnd` |
| `lot.recalled` | MATERIAL | `services/receiving.py:930` | `notify-lot-recalled` | `material`, `batch`, `notice`, `quarantined` |
| `material.change.rejected` | MATERIAL_CHANGE_REQUEST | `services/material_changes.py:386` | stream only | `material`, `reason` |
| `material.change.requested` | MATERIAL_CHANGE_REQUEST | `services/material_changes.py:350` | stream only | `material`, `domains`, `fields` |
| `material.changed` | MATERIAL | `services/material_changes.py:426` | stream only | `material`, `version`, `fields`, `change`, `erpMessage` |
| `material_request.approved` | MATERIAL_REQUEST | `services/mdm.py:239` | `notify-material-approved` | `material`, `materialId` |
| `ml.drift.alert` | ML_MODEL | `services/ml_registry.py:225` | stream only | `code`, `version`, `alerts` |
| `ml.model.activated` | ML_MODEL | `services/ml_registry.py:131` | stream only | `code`, `version` |
| `ml.model.suspended` | ML_MODEL | `services/ml_registry.py:157` | stream only | `code`, `version`, `reason`, `fallbackTo` |
| `mrp.run.completed` | MRP_RUN | `services/erp_import.py:219`, `services/planning.py:440` | `notify-mrp-run` | `plant`, `mode`, `plannedOrders`, `exceptions` |
| `payment.completed` | INVOICE | `services/payables.py:963` | `notify-payment-completed`, `advance-paid` | `payment`, `amountMinor`, `clearingDocument` |
| `payment.returned` | INVOICE | `services/payables.py:999` | stream only | `payment`, `amountMinor`, `reason`, `clearingDocument` |
| `payment_file.acknowledged` | PAYMENT_FILE | `services/bank_files.py:240` | stream only | `run`, `status`, `bankRef`, `totalMinor` |
| `payment_file.generated` | PAYMENT_FILE | `services/bank_files.py:201` | `notify-payment-file` | (see schema) |
| `payment_file.rejected` | PAYMENT_FILE | `services/bank_files.py:240` | stream only | `run`, `status`, `bankRef`, `totalMinor` |
| `payment_file.results_recorded` | PAYMENT_FILE | `services/bank_files.py:320` | stream only | `run`, `credited`, `returned` |
| `payment_file.sent` | PAYMENT_FILE | `services/bank_files.py:240` | stream only | `run`, `status`, `bankRef`, `totalMinor` |
| `pcard.transaction_disallowed` | PCARD_TRANSACTION | `services/ind_general.py:286` | stream only | `card`, `amountMinor`, `reasons` |
| `physical_inventory.posted` | PHYSICAL_INVENTORY | `services/inventory.py:772` | stream only | `inventory`, `plant`, `storageLocation`, `lines`, `differences`, `gainMinor`, `lossMinor`, `accuracyPct`, `erpDocument` |
| `planned_order.firmed` | PLANNED_ORDER | `services/planning.py:471` | `notify-planned-order-firmed` | `qty`, `needDate` |
| `process.definition.published` | PROCESS_DEFINITION | `platform/definitions.py:294` | stream only | `key`, `version`, `baseVersion` |
| `punchout.cart.returned` | PUNCHOUT_SESSION | `services/punchout.py:376` | stream only | `supplier`, `items`, `totalMinor`, `protocol` |
| `purchase_order.cancelled` | PURCHASE_ORDER | `services/order.py:1034` | `contract-consumption`, `notify-po-cancelled`, `erp-po-posting`, `po-transmission-delivery` | `version`, `from`, `reason`, `supplier`, `transmissions` |
| `purchase_order.changed` | PURCHASE_ORDER | `services/order.py:765` | `contract-consumption`, `erp-po-posting` | `version`, `changes` |
| `purchase_order.closed` | PURCHASE_ORDER | `services/order.py:1086`, `services/order.py:1150` | `contract-consumption` | `from`, `reason` |
| `purchase_order.confirmed` | PURCHASE_ORDER | `services/order.py:554` | `notify-po-confirmed` | `version`, `hours` |
| `purchase_order.released` | PURCHASE_ORDER | `services/order.py:437` | `contract-consumption`, `erp-po-posting` | `supplier`, `totalMinor`, `version`, `touchless` |
| `purchase_order.transmitted` | PURCHASE_ORDER | `services/transmission.py:354` | `notify-po-transmitted`, `po-transmission-delivery` | `version`, `channels`, `transmissions` |
| `quality.usage_decision` | GOODS_RECEIPT | `services/receiving.py:414` | `capa-on-rejection`, `supplier-scorecard` | `grId`, `lot`, `accepted`, `rejected`, `defect`, `po`, `lots` |
| `rebate.settled` | REBATE_SETTLEMENT | `services/rebates.py:263` | stream only | `supplierId`, `supplier`, `agreement`, `period`, `amountMinor`, `companyCode`, `erpKey` |
| `requisition.approved` | REQUISITION | `services/requisition.py:664` | `notify-requisition-approved` | `origin`, `totalMinor`, `lines` |
| `requisition.cancelled` | REQUISITION | `services/requisition.py:784` | `notify-requisition-cancelled` | `reason`, `previousStatus` |
| `requisition.submitted` | REQUISITION | `services/requisition.py:366` | stream only | `origin`, `totalMinor`, `chain` |
| `return_delivery.replacement_requested` | RETURN_DELIVERY | `services/receiving.py:555` | `notify-replacement-requested` | `po`, `poLine`, `qty`, `supplierId` |
| `savings.realised` | SAVINGS_INITIATIVE | `services/savings.py:160` | `notify-savings-realised` | `invoice`, `amountMinor` |
| `service_entry.approved` | SERVICE_ENTRY | `services/receiving.py:1037` | `notify-service-entry-approved`, `accessorial-approved` | `po`, `totalMinor` |
| `sod.mitigation.decided` | SOD_MITIGATION | `platform/sod.py:254` | stream only | `mitigationId`, `rule`, `action`, `status`, `requester`, `validUntil` |
| `sourcing.bid.submitted` | SOURCING_EVENT | `services/sourcing.py:380` | `scorecard-responsiveness` | `supplier`, `round` |
| `sourcing.clarification.answered` | SOURCING_EVENT | `services/auction.py:101` | `notify-clarification` | `seq`, `kind`, `question`, `answer`, `ownerId`, `inviteeSupplierIds`, `askedBySupplierId` |
| `sourcing.event.awarded` | SOURCING_EVENT | `services/sourcing.py:1420` | `contract-from-award`, `notify-sourcing-awarded`, `savings-negotiated` | (see schema) |
| `sourcing.event.cancelled` | SOURCING_EVENT | `services/sourcing.py:1481` | `notify-sourcing-cancelled`, `savings-lost` | `from`, `reason`, `round`, `category`, `ownerId`, `inviteeSupplierIds` |
| `sourcing.event.published` | SOURCING_EVENT | `services/sourcing.py:317` | `savings-identify` | `category`, `baselineMinor`, `closeAt`, `lines` |
| `spend.cube.refreshed` | SPEND_CUBE | `services/spend_cube.py:341` | stream only | `mode`, `periods`, `lines` |
| `stock.expired_written_off` | EXPIRY_WRITE_OFF | `services/ind_healthcare.py:440` | stream only | `lines`, `valueMinor` |
| `stock_posting.approved` | STOCK_POSTING | `services/inventory.py:314`, `services/inventory.py:347` | stream only | `posting`, `type`, `approvedBy`, `auto` |
| `stock_posting.posted` | STOCK_POSTING | `services/inventory.py:422` | stream only | `posting`, `type`, `plant`, `valueMinor`, `movements`, `erpDocument` |
| `stock_posting.rejected` | STOCK_POSTING | `services/inventory.py:352` | stream only | `posting`, `type`, `reason` |
| `stock_posting.submitted` | STOCK_POSTING | `services/inventory.py:307` | stream only | `posting`, `type`, `plant`, `valueMinor`, `lines` |
| `stock_reservation.cancelled` | STOCK_RESERVATION | `services/inventory.py:920` | stream only | `reservation`, `material`, `plant`, `openQty`, `reason`, `expired` |
| `stock_reservation.created` | STOCK_RESERVATION | `services/inventory.py:855` | stream only | `reservation`, `material`, `plant`, `qty`, `needDate`, `shortBy` |
| `stock_reservation.issued` | STOCK_RESERVATION | `services/inventory.py:903` | stream only | `reservation`, `material`, `plant`, `issuedQty`, `openQty`, `valueMinor`, `erpDocument` |
| `subcontracting.components_provided` | PURCHASE_ORDER | `services/receiving.py:653` | `notify-components-provided` | `line`, `supplier`, `components` |
| `supplier.assessment.accepted` | SUPPLIER | `services/supplier_mgmt.py:614` | stream only | `kind`, `score` |
| `supplier.development_plan.completed` | DEVELOPMENT_PLAN | `services/supplier_mgmt.py:414` | stream only | `supplierId`, `targetMet` |
| `supplier.invitation.sent` | SUPPLIER_INVITATION | `services/invitations.py:110` | stream only | `legalName`, `categories`, `emailStatus` |
| `supplier.master.changed` | SUPPLIER | `services/master_changes.py:322` | `notify-supplier-master` | `supplierCode`, `change`, `fieldGroup`, `after`, `screening`, `erpMessage` |
| `supplier.registered` | SUPPLIER | `services/invitations.py:239` | `notify-supplier-registered` | `supplierCode`, `channel`, `categories`, `screening` |
| `supplier.segment.changed` | SUPPLIER | `services/supplier_mgmt.py:108` | stream only | `supplier`, `from`, `to`, `method` |
| `supplier.status.changed` | SUPPLIER | `services/supplier.py:794`, `services/supplier.py:60` | `supplier-status-flags` | `supplierCode`, `from`, `to`, `reason` |
| `task.assigned` | TASK | `platform/workflow.py:238` | `notify-task-assigned` | `taskId`, `kind`, `name`, `role`, `objectType`, `objectId`, `objectRef`, `due` |
| `task.escalated` | TASK | `platform/workflow.py:481` | `notify-task-escalated` | `taskId`, `kind`, `name`, `role`, `level`, `objectType`, `objectId`, `objectRef`, `due`, `escalatedTo`, `candidates`, `mode`, `reassignedFrom` |

## Events without an internal consumer

- `accessorial.claimed`: read by the real-time stream and external subscribers only.
- `advance.approved`: read by the real-time stream and external subscribers only.
- `cold_chain.excursion`: read by the real-time stream and external subscribers only.
- `cold_chain.rejected`: read by the real-time stream and external subscribers only.
- `debit_note.posted`: read by the real-time stream and external subscribers only.
- `debit_note.received`: read by the real-time stream and external subscribers only.
- `debit_note.rejected`: read by the real-time stream and external subscribers only.
- `erp.sync.finished`: read by the real-time stream and external subscribers only.
- `finance.period.closed`: Cut-off of a posting period; subscribers (ERP, controlling) freeze their own period.
- `finance.period.reopened`: A closed posting period was reopened with a reason; the audit trail holds who and why.
- `guarantee.expired`: read by the real-time stream and external subscribers only.
- `guarantee.expiring`: read by the real-time stream and external subscribers only.
- `guarantee.verified`: read by the real-time stream and external subscribers only.
- `index.updated`: read by the real-time stream and external subscribers only.
- `invoice.early_payment.accepted`: read by the real-time stream and external subscribers only.
- `invoice.early_payment.offered`: read by the real-time stream and external subscribers only.
- `invoice.paid_in_erp`: read by the real-time stream and external subscribers only.
- `invoice.scf.elected`: read by the real-time stream and external subscribers only.
- `licence.unused_flagged`: read by the real-time stream and external subscribers only.
- `material.change.rejected`: read by the real-time stream and external subscribers only.
- `material.change.requested`: read by the real-time stream and external subscribers only.
- `material.changed`: read by the real-time stream and external subscribers only.
- `ml.drift.alert`: read by the real-time stream and external subscribers only.
- `ml.model.activated`: read by the real-time stream and external subscribers only.
- `ml.model.suspended`: read by the real-time stream and external subscribers only.
- `payment.returned`: A payment returned by the beneficiary bank; finance reverses the ERP clearing document (reconciliation lists it).
- `payment_file.acknowledged`: Status echo of the bank file; the audit trail holds the transition.
- `payment_file.rejected`: Status echo of the bank file; the audit trail holds the transition.
- `payment_file.results_recorded`: The bank's per-payment answer (credited / returned); the audit trail holds each payment's result.
- `payment_file.sent`: Status echo of the bank file; the audit trail holds the transition.
- `pcard.transaction_disallowed`: read by the real-time stream and external subscribers only.
- `physical_inventory.posted`: The count differences are in the ledger and the ERP material document is queued; subscribers (finance, BI) read the stream.
- `process.definition.published`: read by the real-time stream and external subscribers only.
- `punchout.cart.returned`: The requester's browser session receives the cart; nothing else reacts.
- `rebate.settled`: read by the real-time stream and external subscribers only.
- `requisition.submitted`: Approval tasks and the audit trail already carry it; subscribers use it for cycle-time metrics.
- `sod.mitigation.decided`: read by the real-time stream and external subscribers only.
- `spend.cube.refreshed`: read by the real-time stream and external subscribers only.
- `stock.expired_written_off`: read by the real-time stream and external subscribers only.
- `stock_posting.approved`: The posting is posted by a stock poster; the audit trail holds the approver and the rule version.
- `stock_posting.posted`: The stock movements are in the ledger and the ERP material document is queued; subscribers (planning, BI) read the stream.
- `stock_posting.rejected`: The maker sees the rejection on the document; the audit trail holds who and why.
- `stock_posting.submitted`: Approval tasks and the audit trail already carry it; subscribers use it for the inventory approval backlog.
- `stock_reservation.cancelled`: The reservation demand is released for MRP through its demand element; subscribers use the event for dashboards.
- `stock_reservation.created`: The reservation's RESERVATION demand element is what MRP reads; subscribers use the event for requester dashboards.
- `stock_reservation.issued`: The goods issue (201) is in the ledger and the ERP material document is queued; subscribers (consumption analytics) read the stream.
- `supplier.assessment.accepted`: read by the real-time stream and external subscribers only.
- `supplier.development_plan.completed`: read by the real-time stream and external subscribers only.
- `supplier.invitation.sent`: The invitation e-mail is the notification; subscribers use it for onboarding funnel metrics.
- `supplier.segment.changed`: read by the real-time stream and external subscribers only.
