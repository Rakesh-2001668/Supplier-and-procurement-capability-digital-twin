# PIC default decisions

This page lists the defaults the client approved on 9 November 2026. For each one it says what the default is, why we chose it, which rule or
switch changes it, and what the client should still confirm.

All amounts are in Indian rupees. Rules store money in paise (1 rupee = 100 paise). A rule change is a new effective-dated version
(Administration > Rules, or `POST /v1/admin/rules`). Old versions are never edited.

D4 (SAP document types) is described by the SAP mapping team in [PIC_SAP_Document_Types.md](PIC_SAP_Document_Types.md).

## Summary

| Decision | Default | Where to change it |
| --- | --- | --- |
| Invoice approval bands | AP below ₹10 lakh; AP + finance controller from ₹10 lakh; AP + finance controller + CFO from ₹1 crore | Rule `INVOICE-APPROVAL` |
| D1 PO from a planned order | Always through an MRP requisition | Fixed process (BP P02) |
| D2 Out-of-scope inbox tasks | Hidden from the approver | Rule `ABAC` (user attributes) |
| D3 Category check on PO create and release | Off | Rule `ABAC`, actions `PO_CREATE` / `PO_RELEASE` |
| D5 Award on an expired bid offer | Blocked; a category manager may override with a written reason | Rule `SOURCING-POLICY`, key `expiredOfferOverride` |

## Invoice approval bands and the CFO role

**Default.** Accounts payable (AP) approves every matched invoice first. Then the invoice value decides who else approves:

| Gross value (company-code currency) | Approvers after AP |
| --- | --- |
| below ₹10,00,000 | none: AP approval is the only one |
| ₹10,00,000 to ₹99,99,999.99 | Finance controller |
| ₹1,00,00,000 and above | Finance controller, then CFO |

The value is the invoice gross (with GST) in the currency of the company code. A dollar invoice is converted at its fixed rate.

**How it works.**

- The approvers work the invoice in their task inbox, one after the other.
- Nobody approves twice in one chain. The AP approver, the person who captured the invoice and everyone who already approved are excluded
  from the later steps. A person who holds both the finance controller and the CFO role therefore cannot approve both steps.
- Each approver's value limit and company codes apply (rule `ABAC`, action `INVOICE_APPROVE`).
- Delegation of authority works for the CFO step like for any other step.
- If any approver rejects or returns the invoice, it goes back to AP as an `APPROVAL` exception with a payment block. AP clarifies and
  resubmits (a new chain starts), disputes it with the supplier, or rejects the invoice. This is the same at the CFO step.
- Nobody who approved the invoice may release its payment (SOD-09).
- Each step has a due date of `slaBusinessDays` working days (default 2). When it is missed, the approvers get a reminder. From the second
  level the task escalates along rule `ESCALATION` (`managers`). There is no role above the CFO in the default rule, so an overdue CFO step
  only sends reminders. A tenant can add a manager for the CFO in `ESCALATION.managers`.
- An invoice that was approved before the bands took effect keeps its AP-only approval. The bands apply only when an invoice is approved.

**The CFO role.** New built-in role `CFO`. Permissions: read, work tasks, approve invoices, see spend. The CFO cannot capture, post or pay
invoices and cannot change supplier bank details. Assigning the role needs MFA enrolment (like the finance controller), and the role is in the
`MFA.requiredRoles` list of new tenants.

**Who gets the bands.**

- New tenants: yes. The onboarding tool (`python -m app.pic.tools.tenant_admin create`) and any tenant created outside the bundled demo seeds
  start with the bands (`seed/reference.py`, `bootstrap(..., invoice_bands=True)`).
- Existing tenants: no change. Their rule `INVOICE-APPROVAL` keeps `"bands": []` until their administrator publishes a new version.
- Demo tenants AXN and KAC: the dataset pack `approval_bands` (D22) publishes the bands as version `2026.11-BANDS`, effective
  1 November 2026, and creates a CFO user (`cfo@axion.example`, `cfo@kaveri-auto.example`, demo password).

**Rule body.** Rule `INVOICE-APPROVAL`, scoped per company code if needed:

```json
{"bands": [{"fromMinor": 100000000, "approvers": ["FINANCE_CONTROLLER"]},
           {"fromMinor": 1000000000, "approvers": ["FINANCE_CONTROLLER", "CFO"]}],
 "slaBusinessDays": 2}
```

`fromMinor` is the lowest gross value of the band in paise (₹10 lakh = 100000000, ₹1 crore = 1000000000). The band with the highest
`fromMinor` at or below the invoice value applies. To switch the bands off, publish `{"bands": []}`.

**Client to confirm.**

1. The two thresholds (₹10 lakh and ₹1 crore), and whether they are with or without GST (today: with GST).
2. Whether different company codes need different bands.
3. Who escalates an overdue CFO step (today: reminders only).
4. The SLA of 2 working days per step.
5. Who holds the CFO role, and who acts for the CFO on leave (delegation).

## D1: purchase order from a planned order

**Default.** A planned order from MRP is never turned straight into a purchase order. The MRP controller converts it into an MRP requisition
(`planning.convert`). The requisition is approved like any other (rule `DMN-01`). If it is approved at once (auto-approval band), the PO is
created in the same step. Otherwise the buyer orders it after approval. Only the MRP controller (or an agent) can start the conversion; a buyer
gets 403 with rule `P02`.

**Why.** One approval path for all demand. Budget, quote and category checks run on every purchase.

**Change it.** This is a fixed process step (`services/order.py`, `create_from_planned_order`). The approval bands are in rule `DMN-01`.

**Client to confirm.** That planned orders should always pass through a requisition, also for scheduling-agreement materials.

## D2: inbox tasks outside the approver's scope are hidden

**Default.** The task inbox shows a task only if the person could approve it: the right role, not excluded by four-eyes, and inside their ABAC
scope (company code, plant, category, value limit). A task outside the scope is not listed. If someone tries to approve it anyway, the server
refuses with 403.

**Why.** Approvers should not see work they cannot finish. It also keeps documents of other company codes and plants private.

**Change it.** Through the user attributes (`company_codes`, `plants`, `categories`, `value_limit_minor`, `approval_limits`) and rule `ABAC`
(`mode`: `ENFORCE`, `AUDIT` or `OFF`). A user without an attribute is not restricted on that dimension.

**Client to confirm.** That approvers should not see out-of-scope tasks at all (instead of seeing them read-only).

## D3: category check on PO create and release

**Default.** Off. Creating and releasing a PO checks the buyer's company codes and plants (and the value limit on release), not the buyer's
categories.

**Why.** Many buyers order across categories. A category check that is on by default would block them until every buyer has category
attributes.

**Switch it on.** Publish a new version of rule `ABAC` in which `actions.PO_CREATE.check` and `actions.PO_RELEASE.check` also contain
`"category"`. Copy the current body and change only these two lines:

```json
"PO_CREATE":  {"check": ["company_code", "plant", "category"]},
"PO_RELEASE": {"check": ["company_code", "plant", "category"], "valueLimit": true}
```

The version can be scoped to one company code. Then give each buyer the `categories` attribute (`["*"]` for all categories). A buyer without
the attribute stays unrestricted. Every category of the order is checked (each line). To try it first, set `"mode": "AUDIT"`: refusals are only
logged.

**Client to confirm.** Whether to switch it on, for which company codes, and the category list of each buyer.

## D5: award on an expired bid offer

**Default.** Blocked. When a supplier's offer validity (`valid_until` on the bid) has passed, the award on that bid is refused with
`409 BID_OFFER_EXPIRED`. The answer lists the expired bids (supplier, valid until, days expired) and points to the honest way out: a new round
(`POST /v1/sourcing/events/{ref}/rounds`), in which the supplier confirms or extends its offer. The refused attempt is recorded in the audit
trail (`AWARD_BLOCKED_OFFER_EXPIRED`).

**Override.** A category manager of the event's category may still propose the award with a written reason of at least 20 characters
(field `expired_offer_override` on `POST /v1/sourcing/events/{ref}/award`). Then:

- the award decision carries exception `BID_OFFER_EXPIRED` with who overrode, when, why and which bids;
- the audit trail records `AWARD_EXPIRED_OFFER_OVERRIDDEN`;
- event `sourcing.award.offer_expiry_overridden` is emitted;
- the award always goes to the approvers of rule `AWARD-APPROVAL`, and the person who overrode cannot approve it.

A buyer who owns the event cannot override (403 `OVERRIDE_NOT_ALLOWED`). If an offer expires while the award waits for approval, the approver
gets the same 409 and returns the award.

The award screen shows the block, the expired bids, a "Start a new round instead" button and, for a category manager, the override reason.

**Why.** An expired offer is not binding. Awarding on it risks a price the supplier no longer honours. The override covers the real case of a
supplier that confirmed the price in writing.

**Change it.** Rule `SOURCING-POLICY`, key `expiredOfferOverride`:

```json
"expiredOfferOverride": {"roles": ["CATEGORY_MANAGER"], "minReasonChars": 20, "requiresApproval": true}
```

`roles: []` means nobody may override. `requiresApproval: false` lets an override follow the normal value band only.

**Client to confirm.** Which role may override (category manager, or the CPO), the minimum reason length, and that an override always needs
approval.
