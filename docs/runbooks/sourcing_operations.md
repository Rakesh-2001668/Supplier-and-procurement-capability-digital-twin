# Runbook: strategic sourcing operations (M05, flow F3)

Audience: category managers, buyers, evaluators, tenant administrators and the engineer on call. Code: `backend/app/pic/services/sourcing*.py`,
`auction.py`, `should_cost.py`; rule sets `SOURCING-POLICY`, `SOURCING-TCO`, `AWARD-APPROVAL`, `AWARD-RISK`, `AUCTION`. Analysis and proof:
`docs/PIC_Strategic_Sourcing_Analysis.md`. Times are Indian Standard Time; a deadline sent without a zone is read as IST.

## 1. Run an event end to end

| Step | Who | Command (API) | What the platform checks |
|---|---|---|---|
| 1 Build | Category manager or buyer (`sourcing:manage`) | `POST /v1/sourcing/events` (or `POST /v1/sourcing/templates/{code}/events`, `POST /v1/sourcing/events/{ref}/clone`) | approved requirement lines only (P06), one company code, line category (policy `lineCategoryCheck`), invitees Qualified/Preferred or Conditional with a waiver, no duplicate invitee, criteria unique and whole-number weights 0-100, scoring method, baseline method, ABAC `SOURCING_CREATE` (category, plant, company code) |
| 2 Publish | Event owner or a category manager of the category | `POST .../publish` (`Idempotency-Key`, `If-Match` from the event's `ETag`) | weights add up to 100 and are locked, RFQ/auction carry a PRICE_TCO weight, purpose code (P01), mandatory fields of the type (`need_date`), minimum open hours, clarification deadline before the bid deadline, bids close before the need date, category budget (soft stop needs `budget_justification`, hard stop refuses) |
| 3 Bid | Invited supplier (`bid:submit`) | `POST .../bids`, `POST .../bids/withdraw` | sealed until the close; replace as often as you like before the close; plausible price (against the baseline and an absolute limit), one currency per bid with a rate on the pricing date, valid offer date beyond the close; a late, uninvited, blocked or disqualified supplier is refused **and logged** |
| 4 Clarify | Suppliers ask, owner answers | `POST .../clarifications`, `.../{seq}/answer` | answers are published to every invitee without the asker's name; questions close at the clarification deadline |
| 5 Close and open | Timer at the close time; two people when the rule says so | `POST .../close`, `POST .../open` | bids are unsealed only now (`BIDS_UNSEALED` audit entry, `sourcing.bids.unsealed` event); with two-person opening the event waits in CLOSED until two different people have called `open` |
| 6 Evaluate | Evaluators (`sourcing:evaluate`) | `POST .../declarations`, `POST .../scores`, `GET .../comparison` | every evaluator declares a conflict of interest first; scores 0-100; technical gate; ranking by total cost with a fixed tie-break |
| 7 Scenarios | Event owner | `POST .../scenarios` (lowest cost, best value, capacity constrained), `POST .../scenarios/custom` (a split you enter) | capacity from the digital twin and the bid, share bounds, supplier count, MOQ, risk caps; risk score and savings per scenario |
| 8 Award | Event owner proposes; approvers by value band decide | `POST .../award`, then the approval tasks | rationale for exceptions, authority band, SoD (sole evaluator cannot award, approver is not the proposer), conflict declaration |
| 9 Hand-off | Automatic | `GET .../handoff` | contract drafts per awarded supplier, price validities, quota arrangement and source list on activation, regret letters, savings initiative |

States: `DRAFT > PUBLISHED > OPEN > CLOSED > UNDER_EVALUATION > AWARD_PENDING > AWARDED`, `CANCELLED` from any state before the award. `PUBLISHED`
is a resting state when the event has a scheduled opening (`open_at`): suppliers see the requirement and may ask questions, bids are accepted from
`open_at`. Without `open_at` an event publishes and opens at once. Every illegal command answers 409.

## 2. Sealed bids and the opening

* A bid is stored encrypted; only its SHA-256 is readable. Nothing of the commercial content can be read before the opening through any route: bids
  list, line matrix, comparison, CSV export, event view, audit trail or lineage.
* An attempt to read early answers `423 BIDS_SEALED` and writes `BID_ACCESS_DENIED` to the audit trail (also: `LATE_BID_REFUSED`,
  `UNINVITED_BID_REFUSED`, `INELIGIBLE_BID_REFUSED`, `DISQUALIFIED_BID_REFUSED`). Review them under `GET /v1/sourcing/events/{ref}/history`.
* **Two-person opening.** Switch it on for every event with `SOURCING-POLICY.twoPersonOpening = true` or for one event with
  `constraints.two_person_opening = true`. At the close the event stays CLOSED and every bid sealed. Each opener calls `POST .../open` once; the
  second, different opener unseals the bids and the event moves to UNDER_EVALUATION. The first opener cannot open twice (`ALREADY_OPENED_BY_YOU`).
* A supplier may replace its bid until the close (the number of edits is kept) or withdraw it (the content is destroyed, never opened) and bid again.

## 3. Reverse auctions

Settings come from rule `AUCTION`, are overridable per event while it is a draft (`PUT .../auction`) and are frozen at publish: minimum decrement %,
soft close (`triggerMinutes`, `extensionMinutes`), `showRank`, `showBestPrice`, payment terms and lead time of the auction bids, and `ceilingMinor`
(no bid above it). The soft close extends the end at most `SOURCING-POLICY.maxExtensions` times (12), so an auction cannot run for ever. The ladder is
an append-only ledger. At the end each supplier's last price becomes a sealed bid and the event is evaluated like any other. English (descending)
auctions only; Dutch and sealed-then-auction are not built.

## 4. Scoring weights, methods and the technical gate

* Weights are whole numbers 0-100, add up to 100 at publish and are locked from then on. Criteria: `PRICE_TCO` (always calculated), manual criteria
  (QUALITY, DELIVERY, TECHNICAL, ESG, RISK ...) and data-driven ones (`data_source` SCORECARD, ESG, RISK, frozen at the close).
* **Price score** by the event's `scoring_method`: `LOWEST_RATIO` (lowest total cost divided by this bid's, times 100; the default), `MIN_MAX`
  (highest minus this over highest minus lowest, times 100), `RANK` (100 times (n - rank + 1) / n). Per line, value-weighted over the lines.
* **Technical gate.** A criterion with `min_score` is a precondition: a bidder whose average evaluator score is below it, or not scored yet, cannot be
  awarded (`TECHNICAL_GATE`) and is left out of every scenario.
* **Ties.** Equal total cost is ranked by weighted score, then the earlier submission, then supplier code. `tiedWithPrevious` is shown.
* **Disqualification** (`POST .../disqualify`, written reason of a sentence): the bid stays on record, leaves the ranking, the scenarios built on it
  become stale, the supplier is told, and it cannot bid again in a later round.

## 5. The TCO rule set

`tco = price + freight + duty + packaging + carrying(lead time, safety stock) + quality(ppm x cost of poor quality) - payment-term value`, per base unit
of measure in paise. Every component is traced (value, status, formula, inputs) on the bid line and shown in the comparison and the CSV export;
`sum(rounded components) + rounding = total`. Statuses: BID, ESTIMATED, TWIN/SCORECARD/RULE_DEFAULT, INCLUDED, NOT_QUOTED, NOT_APPLICABLE and **MISSING**. A
missing input makes the line `tco_incomplete`: it is not silently zero, the matrix flags it, and an award on it needs the written rationale.

Change the rule: `POST /v1/admin/rules` with key `SOURCING-TCO` and a new effective-dated version (the body is validated). An event takes a copy of the
values when it is created (`tco_params`), so a new version never moves a running event; an event can override single values at creation
(`tco_params`, e.g. `{"carryingRatePct": "20"}`; the three original snake-case keys are still accepted).

| Key | Meaning |
|---|---|
| `carryingRatePct`, `costOfCapitalPct` | annual inventory carrying rate and cost of capital |
| `copqPerDefectMinor` | cost of poor quality of one defective unit; quality cost = ppm / 1,000,000 x this |
| `includeSafetyStock`, `maxSafetyDays` | carrying also covers the days the safety stock lasts (safety stock / daily demand, capped) |
| `defaultPpm`, `ppmFromScorecardPeriods` | PPM when the twin has none: mean of the last N scorecards, else the default, else MISSING |
| `buyerPaysFreightIncoterms`, `freightEstimatePct`, `deliveredIncoterms` | freight estimated as a percentage of the price when the buyer carries it and the bid gives none |
| `dutyRates`, `dutyBasis` | effective customs duty % by HS prefix (longest prefix wins) on price + freight; an import without a rate is MISSING |
| `taxCreditable` | GST is credited: compare prices without tax |
| `missingInput` | `FLAG` (default) or `REJECT` (the bid line is refused) |

Try a bid line before an event exists: `POST /v1/sourcing/tco/simulate`.

## 6. Should-cost, benchmarks and the baseline

* **Models** (`POST /v1/sourcing/should-cost/models`, a new version each time, never an edit): components `QTY_RATE` (quantity x yield loss x rate x
  index factor), `TIME_RATE`, `FIXED`, `PCT_OF`, a margin 0-100 %, material rates linked to a published index (`index_value`): the rate follows
  `index(on) / index(baseDate)`. Evaluate with `POST /v1/sourcing/should-cost/evaluate`; attach to an event with `should_cost_model` (or the original
  die-casting `should_cost_params`).
* **Benchmarks.** `GET /v1/sourcing/benchmarks` shows last price, 12-month quantity-weighted average of orders, market, peer/catalogue prices and the
  band they span. Record market or peer prices with `POST /v1/sourcing/benchmarks`.
* **Baseline** of an event (`baseline_method`): `LAST_PRICE`, `WEIGHTED_AVG`, `SHOULD_COST`, `MARKET_INDEX` (derived per line when no price is given),
  `BUDGET`, `MANUAL` (given). The method is stored on the event and on the savings initiative. A negotiated saving is (baseline - awarded price) x annual
  quantity; an award above the baseline is a cost increase: it is not booked as a negative saving, the audit trail records it and the award needs a rationale.

## 7. Award governance

* **Authority.** Approval route by annual value from rule `AWARD-APPROVAL` (default: up to 50 lakh the category manager; above it category manager, CPO
  and finance controller). A non-lowest award, an award on limited competition or a cost increase (and, when the policy says so, incomplete TCO or unverified capacity) always goes to
  the approvers even below the threshold. The band, chain and value are stored on the decision (`authority`); the exceptions in `exceptions`.
* **Written rationale** (at least `minRationaleChars` characters, default 15) is required for the exceptions `NOT_LOWEST`, `LIMITED_COMPETITION`
  (fewer valid bidders than `minBidders`), `NEGATIVE_SAVINGS`, and `INCOMPLETE_TCO` / `UNVERIFIED_CAPACITY` when `incompleteTcoNeedsRationale` / `unverifiedCapacityNeedsRationale` are on (off by default so older data without PPM or capacity keeps awarding; the KAC rule version turns both on). Both are always shown and recorded as exceptions. `LEAD_TIME_AFTER_NEED` is recorded (policy
  `leadTimeCheck` WARN) or refused (ENFORCE).
* **Blocks.** An award is refused when an awarded bid is no longer evaluated, its offer validity has ended, it failed or has not been scored on the
  technical gate, or any manual criterion is unscored (`requireAllCriteriaScored`).
* **Conflict of interest.** Every evaluator declares first (`POST .../declarations`); a declared conflict bars scoring and the award proposal and cannot be
  withdrawn. The proposer also gives a declaration with the award.
* **Segregation of duties.** SOD-05: the sole evaluator of an event cannot award it; the approver is never the proposer.
* **Capacity.** The optimiser uses the lower of the bid capacity and the twin's free capacity. Capacity nobody verified is assumed enough and flagged;
  `SOURCING-POLICY.unverifiedCapacity = BLOCK` treats it as zero.
* **Manual split** (`POST .../scenarios/custom`): percentages or monthly quantities per supplier (and line); the shares must add up to exactly 100 %.

## 8. After the award

`sourcing.event.awarded` creates one contract draft per awarded supplier (prices published to source determination when the contract is activated),
the savings initiative moves to Negotiated with the baseline method, every bidder that was not awarded gets a **regret letter** (its own rank and
reason, never a competitor's data; a disqualified bidder gets the reason), and on contract activation the quota arrangement (shares as awarded,
running counters at zero) and a source-list entry are created. `GET .../handoff` shows contracts, price publication, quota counters, source-list entries
and whether a purchase order can be released today (`poReleaseEligible` per contract). A cancelled event releases its requirement lines and marks the
savings initiative lost; an awarded event cannot be cancelled (end the contract instead).

## 9. Templates, cloning and exports

* Template: `POST /v1/sourcing/templates` (criteria summing to 100, constraints, TCO overrides, scoring and baseline method, invitation filter,
  auction settings). `POST /v1/sourcing/templates/{code}/events` builds a Draft with the requirement lines and the dates of the day; without
  `invitees` the filter picks qualified suppliers by risk.
* Clone: `POST /v1/sourcing/events/{ref}/clone` (re-tender after a cancellation, next round of a contract); suppliers that lost their qualification are
  dropped and listed; `cloned_from` keeps the link.
* Export: `GET /v1/sourcing/events/{ref}/comparison.csv` after the opening; the file's SHA-256 is in the header `X-Content-SHA256` and in the audit entry
  `COMPARISON_EXPORTED` (rows, bytes, who). The same data gives the same file.

## 10. KPIs and the pipeline

`GET /v1/kpis?module=M05` (also on the dashboards): sourcing cycle time (publication to the approved award), competitive events %, negotiated
savings %, bidders per event, supplier participation %, award-to-contract lead time, sourced savings realised %, awards to a non-lowest bid %.
`GET /v1/sourcing/pipeline` lists events per stage with value, age and next step.

## 11. Incidents

| Symptom | Likely cause | Action |
|---|---|---|
| `423 BIDS_SEALED` on a closed event | two-person opening pending | two different `sourcing:manage` users call `POST .../open` |
| A bidder's bid is `INVALID` at the opening | no line could be evaluated (for example no exchange rate for its currency on the pricing date) | the audit entry `BID_INVALID` lists the rejected lines and why; add the rate and start a new round |
| Award refused `UNSCORED_CRITERIA` | an evaluator has not scored a manual criterion | score it, or lower its weight in a new event; the weights of a published event are locked |
| Award refused `TECHNICAL_GATE` | the bidder scored below `min_score` or has no score | score it, or take another scenario |
| `TCO` shows `incomplete` | missing PPM, duty rate or similar | add the twin/scorecard data or the rate to `SOURCING-TCO`, or award with a written rationale |
| `BUDGET_JUSTIFICATION_REQUIRED` at publish | the event takes the category budget over 100 % | add `budget_justification` (soft stop) or ask finance to raise the plan (hard stop) |
| A close timer did not fire | worker not running | `POST /v1/admin/ops/tick`; closing is idempotent and `POST .../close` also works for the owner |
