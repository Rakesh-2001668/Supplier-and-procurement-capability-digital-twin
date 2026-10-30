# PIC Pending Workflows

AlphaHelion Procurement Intelligence Cloud, 30 Oct 2026. Every workflow and process capability still open against the
Technical Document (TD) and the Blueprint (BP). Source: the requirement matrix
([PIC_Spec_Traceability_Matrix.md](PIC_Spec_Traceability_Matrix.md)), re-checked against the current code.

**Already complete and not listed here:** the nine core workflows F1–F9 (84 steps, all 13 decision points tested both ways),
and the ERP data loaders for vendors, materials, contracts, open POs, open payables and spend history with GL tie-out.

Status key: **Not built** · **Partial** (part exists; the gap is stated) · **Needs client** (cannot finish without the
client's system or decision).

Size: S ≤ 1 day, M 2–5 days, L 1–3 weeks.

## 1. Scheduled and automatic workflows

| # | Workflow | Spec | Status | Size |
|---:|---|---|---|---|
| 1 | Payment-due trigger that starts or proposes the payment run | TD §8 F7 | Not built; runs are manual | S |
| 2 | Nightly ERP reconciliation per company code | TD §12.2, P13 | Partial: manual run only | S |
| 3 | Scheduled MRP runs | TD §8 F1 | Partial: started by hand or API | S |
| 4 | Monthly supplier scorecard recalculation | BP M06 | Partial: event-driven only | S |
| 5 | Data retention purge and audit archive | TD §15, BP M13 | Not built; report only | M |
| 6 | Expired idempotency-record purge (24 h) | TD §10 | Not built | S |

## 2. Procure-to-pay workflows

| # | Workflow | Spec | Status | Size |
|---:|---|---|---|---|
| 7 | Debit notes | BP M10 | Not built; credit notes only | M |
| 8 | Inbound EDI invoices (INVOIC) | TD §12.3, BP M10 | Not built | M |
| 9 | Hard block on POs to unqualified suppliers, with a one-time-vendor exception | BP M06 | Partial: risk points only | S |
| 10 | PO price check against last price (+5%), and contract +2% band | BP §24, M08 | Partial: contract tolerance only | S |
| 11 | Sales-order account assignment on requisitions | BP M04 | Not built | S |
| 12 | Request templates for services, IT, marketing, facilities | BP M04 | Not built | M |
| 13 | Receipt tolerances per material or supplier | BP M09 | Partial: rule level only | S |
| 14 | Capitalisation data in the goods-receipt ERP posting | BP §22 | Not built | S |
| 15 | Supply-chain finance hooks | BP M10 | Not built | M |
| 16 | Rule-configurable mandatory fields per document | TD §6, P14 | Not built | M |

## 3. Master data workflows

| # | Workflow | Spec | Status | Size |
|---:|---|---|---|---|
| 17 | Change request for an existing material, with impact on open POs, contracts and catalogues | BP M03 | Not built | M |
| 18 | Field-level ownership and approval by material type | BP M03 | Partial: domain level only | M |

## 4. Sourcing and contract workflows

| # | Workflow | Spec | Status | Size |
|---:|---|---|---|---|
| 19 | Multi-item and lot bidding | BP M05, TD §9.3 | Not built; one item per event (decision needed) | L |
| 20 | Requirement bundling from requisitions, MRP demand or category plans | BP M05 | Not built | M |
| 21 | Risk constraints in award optimisation | TD §9.3 | Not built | S |
| 22 | Invitation filters by segment and risk | BP M05 | Partial: no filter on screen | S |
| 23 | ESG and risk criteria in bid scoring | BP M05 | Partial: no data source | M |
| 24 | Master agreement and NDA contract types | BP M07 | Not built | M |
| 25 | Contract templates by jurisdiction | BP M07 | Not built | S |
| 26 | Supplier rebates | BP M07 | Not built | M |
| 27 | Clause extraction when migrating contracts | TD §12.4 | Not built; contract data loads, clauses do not | M |

## 5. Supplier management workflows

| # | Workflow | Spec | Status | Size |
|---:|---|---|---|---|
| 28 | Supplier segmentation (strategic, leverage, bottleneck, routine) | BP M06 | Not built | S |
| 29 | Supplier development plans | BP M06 | Not built; CAPA exists | M |
| 30 | Scorecard responsiveness and ESG measures | BP M06 | Not built | S |
| 31 | Geographic, single-source and cyber risk signals | BP M06 | Not built | M |

## 6. Spend and savings workflows

| # | Workflow | Spec | Status | Size |
|---:|---|---|---|---|
| 32 | Savings pipeline tracker (screen SPD-08) | BP M01 | Not built | S |
| 33 | Spend cube: price variance, aggregation, PO commitments, supplier parent/child | BP M01 | Partial | M |
| 34 | Savings P&L and budget impact view | BP M11 | Not built | S |

## 7. Industry workflows

| # | Industry | Workflow | Status | Size |
|---:|---|---|---|---|
| 35 | Manufacturing | Self-billing (ERS) on scheduling agreements | Not built | S |
| 36 | Manufacturing | Kanban and reorder-point planning for C-parts | Not built | M |
| 37 | Manufacturing | Weekly MRP buckets by MRP type | Not built; daily only | S |
| 38 | Construction | Advance payment and recovery | Not built (rule flag unused) | M |
| 39 | Construction | Performance bank guarantee tracking | Not built | S |
| 40 | IT services | Licence utilisation and unused-licence flag | Not built | S |
| 41 | Logistics | Detention, demurrage and accessorial charges | Not built (flag unused) | M |
| 42 | Healthcare | Clinical sign-off on awards | Not built (flag unused) | S |
| 43 | Healthcare | Cold-chain tracking | Not built | M |
| 44 | Healthcare | Par-level planning | Not built | S |
| 45 | General | P-card limits | Not built | M |

## 8. Platform and governance workflows

| # | Workflow | Spec | Status | Size |
|---:|---|---|---|---|
| 46 | Segregation-of-duties conflict approval (mitigating approval) | TD §14, P09 | Not built; conflicts only block | S |
| 47 | Segregation-of-duties checks for AI agents | TD §13, BP §25 | Partial: guard has no SoD check and is called at 2 sites | M |
| 48 | Overdue-task reassignment | TD §8 | Partial: manager added, not reassigned (decision needed) | S |
| 49 | Editable, versioned workflow definitions and designer | TD §8, BP M13 | Not built; flows are code | L |
| 50 | Configurable ERP field mappings | BP M13 | Not built; fixed in code | M |
| 51 | AI kill switch per company, and drift-triggered suspension | TD §13 | Partial | S |
| 52 | Guided Buying agent (AG-03) wired in | BP §25 | Partial: exists, never invoked | S |
| 53 | Event consumers for the AI services and the catalogue | TD §11 | Partial: 10 of 23 catalogue events consumed | M |

## 9. Needs the client's systems

Adapters or simulators exist; these cannot be finished without the client.

| # | Workflow | Spec | Needs |
|---:|---|---|---|
| 54 | Real SAP S/4 posting (OData/IDoc) | TD §12.1 | SAP sandbox |
| 55 | Live inbound ERP sync (masters, stock, open POs, payment status) | TD §12.1 | SAP sandbox |
| 56 | Supplier Capability Digital Twin connector | TD §12.3 | Twin API |
| 57 | Financial-risk and news feeds | TD §12.3 | Provider licence |
| 58 | AI models (embeddings, gradient-boosted forecast, LLM redline, price trend, late delivery) | TD §13 | LLM gateway and training data |

## 10. Not in the specs, but enterprise buyers expect it

| # | Workflow | Why | Size |
|---:|---|---|---|
| 59 | Delegation of authority (out-of-office approvers) | The specs and the code have neither; approvals wait until escalation when an approver is away | S |

## Totals

| Group | Items |
|---|---:|
| Scheduled and automatic | 6 |
| Procure-to-pay | 10 |
| Master data | 2 |
| Sourcing and contracts | 9 |
| Supplier management | 4 |
| Spend and savings | 3 |
| Industry | 11 |
| Platform and governance | 8 |
| Needs the client | 5 |
| Not in the specs | 1 |
| **Total** | **59** |

## Suggested order

1. **Before any real client:** items 1–6, 9, 10, 46, 47, 48, 59.
2. **Client-facing basics:** items 7, 16, 17, 28, 32, 53.
3. **Pilot industry only:** the items in §7 for that client.
4. **When the client's systems are available:** §9 and item 8.
5. **Later, if wanted:** items 19, 49, 50.
