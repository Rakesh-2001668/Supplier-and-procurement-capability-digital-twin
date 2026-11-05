# PIC Strategic Sourcing Analysis: M05 Strategic Sourcing (flow F3), second pass

Scope: Blueprint M05 (section 11: capabilities, design notes, screens SRC-01..05, business rules, KPIs), flow F3 (section 21.3), the hand-offs from MRP and
requisitions (sections 6, 8, 9), M11 baselines (section 17), roles and SoD (sections 4, 5), and Technical Document sourcing-svc (sections 5, 6.1 guards, 7,
9.2 source determination and quota arrangements, 9.3 TCO and award optimisation, 10, 11, 12.4 should-cost). Code: `backend/app/pic/services/sourcing.py`,
`sourcing_tco.py`, `sourcing_analysis.py`, `sourcing_templates.py`, `sourcing_kpi.py`, `sourcing_notify.py`, `sourcing_handoff.py`, `should_cost.py`,
`auction.py`, `source.py`, `api/source_contract.py`, `api/source_ops.py`, `platform/sourcing_defaults.py`, migration `0022`.
Method: re-derived every requirement from the two specifications, read every code path, wrote adversarial probes and ran them **against the original
code (git HEAD b129437, extracted to a scratch directory, on the Axion seed, every probe rolled back)** to separate real defects from suspicions, fixed what was
broken, built what was missing, and proved it with `backend/tests/pic/test_sourcing_second_pass.py` (41 tests, named `test_src2_*`) and the dataset
tests `test_datasets_sourcing_ops.py` (17). The Axion signature case (RFQ-2231: Kovai Diecast 412 then 405, Trichy Forge 398, Salem Light Alloys 405;
should-cost 391; baseline 410; dual source 60 % at 398 and 40 % at 405) is unchanged and its tests are untouched.

Status legend: **VERIFIED** = covered by a named test that passes; **CODE ONLY** = implemented and read, no automated test; **PARTIAL** = part of the rule is
built; **MISSING** = not built; **WRONG** = built but did not do what the specification says (before this pass). Test keys: **S2** =
`test_sourcing_second_pass.py`; **R34** = `test_review_f3_f4.py`; **W1S** = `test_wave1_sourcing_contracts.py`; **SOP** = `test_source_ops.py`;
**CTL** = `test_controls.py`; **SIG** = `test_signature_case.py`; **DSO** = `test_datasets_sourcing_ops.py`; **BR** = `test_datasets_branches.py`.

## 1. What the specification requires

| Source | Requirement |
|---|---|
| BP 11.1 | Event types RFI, RFQ, RFP, reverse auction, multi-round, lot/item bidding; requirement bundling from PRs, MRP demand or category plan; invitation from the qualified list with segment and risk filters; weighted scoring (price/TCO, quality, delivery, technical, ESG, risk); should-cost and price benchmarks; TCO with freight, duty, inventory carrying, quality cost; award scenarios (lowest cost, best value, split/dual source, capacity-constrained optimisation); award approval and notification, outcome flows to contract or PO; sealed bids, clarifications, Q&A log |
| BP 11.2 | Signature case RFQ-2231 (412 / 398 / 405, should-cost 391, baseline 410, dual source 60 % at 398 and 40 % at 405 negotiated from 412); TCO = price, freight, duty, packaging, inventory carrying, quality cost (PPM x cost of poor quality), payment-term value |
| BP 11.3 | SRC-01 project cockpit, SRC-02 event builder, SRC-03 bid comparison and TCO, SRC-04 award scenario studio, SRC-05 award approval (rationale, conflicts declaration, approvers, audit) |
| BP 11.4 | Only Qualified (or Conditional with waiver) suppliers are invited; bids stay sealed until close, early access blocked and logged; weights locked once published; non-lowest award needs a written rationale; award above the threshold needs category head and finance |
| BP 11.5 | KPIs: sourcing cycle time, competitive events %, negotiated savings %, bidders per event |
| BP 21.3 F3 | Event, build and invite, clarifications and sealed bids, normalise bids / TCO / should-cost, another round or auction, award scenarios, "award > 50 L or not lowest?" gateway, approve, notify and hand off to contract or PO; savings recorded as "negotiated" |
| BP 4/5 | SOD-05 award sourcing event / sole evaluator; roles category manager, buyer, evaluators, approvers; ABAC on category and value |
| BP 17 (M11) | Baseline method, negotiated savings from the award, realisation from posted invoices |
| TD 5 / 6 | Sourcing event states Draft, Published, Open, Closed, Under Evaluation, Award Pending, Awarded or Cancelled; bid and award_decision entities |
| TD 6.1 | Draft to Published: budget check passed (or soft-stop justification), mandatory fields, purpose code (P01), all invitees Qualified/Conditional with waiver, scoring weights sum to 100 and are then locked; Closed to Under Evaluation: close time reached, bids unsealed only now (audit event bids.unsealed) |
| TD 9.2 | Source determination: contract line, quota arrangement (split by % with running counters), source list, info record, buyer queue; exclude Blocked / not Qualified |
| TD 9.3 | tco = price + freight + duty + packaging + carrying(lead time, safety stock) + quality(ppm x cost of poor quality) - payment-term value(days, cost of capital); score = sum(weight x normalised); award MIP: minimise sum(x_s tco_s Q) s.t. sum x = 1, x_s Q <= verified free capacity (twin), x_s >= min_share if selected, count <= max_suppliers, risk constraints; RFQ-2231: Q = 90,000 / month, Trichy capacity 60k, x_T <= 0.667, chosen 60/40, weighted 400.8 |
| TD 10 / 11 | `POST /v1/sourcing/events`, `/publish`, `/bids`, `/award`; Idempotency-Key and ETag/If-Match on commands; events sourcing.event.published / awarded, sourcing.bid.submitted |
| TD 12.4 | Should-cost: parametric model by commodity (weight, alloy/material index, cycle time, machine rate, overhead), run by the Bid Analysis Agent |

## 2. Traceability: specification step to code to proof

"Before" is the status of the original code (HEAD b129437); "Now" is after this pass. New tests are in S2.

| # | Spec rule / step | Code | Proof | Before | Now |
|---|---|---|---|---|---|
| T01 | Event types RFI, RFQ, RFP, REVERSE_AUCTION, validated | `sourcing.create_event`, `EventIn` pattern | S2 `event_definition_checks` | PARTIAL (API only: the service accepted "RFX") | VERIFIED |
| T02 | Reverse auction (English): decrement, rank visibility, soft close, ledger append-only, last price becomes the sealed bid | `auction.py` | SOP `reverse_auction_*`, S2 `auction_soft_close_*` | VERIFIED | VERIFIED |
| T03 | Auction soft close cannot go on for ever | `auction.place_bid`, `SOURCING-POLICY.maxExtensions` | S2 `auction_soft_close_stops_extending_*` | WRONG (unbounded: 30 extensions after 30 bids, reproduced) | VERIFIED |
| T04 | Auction ceiling (reserve) price; implausible auction price refused | `AuctionSettings.ceilingMinor`, `place_bid` | S2 same | MISSING | VERIFIED |
| T05 | Dutch auction, sealed-then-auction | none | - | MISSING | MISSING |
| T06 | Multi-round negotiation, earlier rounds superseded, scores carry over | `new_round`, `_unseal`, matrix | R34 `manual_scores_carry_over*`, SIG | VERIFIED | VERIFIED |
| T07 | Lot / item bidding: per-line bids, bundle discount, all-or-nothing, partial bids ranked below complete ones | `_check_bid_lines`, `_AwardContext` | W1S (lot tests) | VERIFIED | VERIFIED |
| T08 | Requirement bundling from PRs, MRP demand, category plan | `bundle_candidates`, `bundle_preview`, `create_event` | W1S | VERIFIED | VERIFIED |
| T09 | Invitation gate: Qualified/Preferred or Conditional with waiver; re-checked at bid and award | `create_event`, `_require_eligible` | R34 `malformed_bids*`, `event_commands*` | VERIFIED | VERIFIED |
| T10 | Duplicate invitee refused | `create_event` | S2 `event_definition_checks` | WRONG (IntegrityError, 500, reproduced) | VERIFIED |
| T11 | Invitation filters by segment, risk, open signals | `invitee_candidates`; template filter | W1S, S2 `templates_and_clones` | VERIFIED | VERIFIED |
| T12 | Sealed bids: encrypted, hash only in clear, edit before close | `submit_bid` | S2 `supplier_can_replace_and_withdraw*` | PARTIAL (edit without a trace) | VERIFIED |
| T13 | Supplier withdraws a sealed bid; content destroyed unread | `withdraw_bid`, `POST .../bids/withdraw` | S2 same | MISSING | VERIFIED |
| T14 | Late bid, uninvited, blocked, disqualified supplier refused **and logged** | `_bid_gate`, `log_refusal` | S2 `late_uninvited_ineligible_and_early_attempts_are_logged` | WRONG (refused, no trail, reproduced) | VERIFIED |
| T15 | Bid line validation: finite numbers, plausible against baseline and absolute limit, limits on terms and lead time | `_check_bid_lines`, `SOURCING-POLICY.priceBand` | S2 `bid_lines_refuse_nonfinite_*` | WRONG (Infinity accepted then silently INVALID at the close; 100x the baseline accepted, reproduced) | VERIFIED |
| T16 | Bid currency, FX at the event's reference date, one currency per bid | `normalise_price`, `fx_rate_on`, `bid_line.currency/fx_rate` | S2 `tco_components_follow_the_rule_set`, `bid_lines_refuse*` | MISSING | VERIFIED |
| T17 | Price per base unit (UoM factor), tax inclusion (GST creditable), incoterm adjustment | `normalise_price`, `compute` | S2 `tco_components_*` | MISSING | VERIFIED |
| T18 | Offer validity date; expired offer cannot be awarded | `submit_bid(valid_until)`, `award_gate` | S2 `bid_lines_refuse*`; award block CODE ONLY | MISSING | PARTIAL (checked at submission, enforced at award; no automatic expiry job) |
| T19 | Alternate offers per line | none | - | MISSING | MISSING |
| T20 | Prices rounded to paise correctly | `normalise_price` (half-up) | S2 `prices_round_half_up_*` | WRONG (truncated 398.456 to 39845, reproduced) | VERIFIED |
| T21 | Clarification / Q&A log, answer broadcast without asker | `auction.ask/answer/withdraw` | SOP `clarifications_visibility_and_anonymity` | VERIFIED | VERIFIED |
| T22 | Clarification deadline before the bid deadline | `clarification_close_at`, `auction.clarification_deadline` | S2 `publish_guards_*` | MISSING | VERIFIED |
| T23 | Weights sum to 100 at publish, locked; entry validation (unique codes, whole numbers 0-100) | `publish`, `_check_criteria` | R34, S2 `event_definition_checks` | PARTIAL (publish only) | VERIFIED |
| T24 | Price normalisation methods: lowest ratio, min-max, rank | `price_scores`, `scoring_method` | S2 `price_scores_by_method_*` | PARTIAL (lowest ratio only) | VERIFIED |
| T25 | Deterministic ranking, tie-break rule | `evaluation_matrix` | S2 `equal_total_cost_is_ranked_*` | WRONG (database order, reproduced) | VERIFIED |
| T26 | Evaluator scores 0-100, finite | `score` | S2 `scores_are_numbers_*` | WRONG (150 accepted by the service, reproduced) | VERIFIED |
| T27 | Technical gate (`min_score`) before commercial award | `Criterion.min_score`, matrix `technicalGate`, `award_gate` | S2 `technical_gate_and_disqualification*` | MISSING | VERIFIED |
| T28 | Two-envelope evaluation (technical opened before price) | none | - | MISSING | MISSING |
| T29 | Disqualification with written reason, stale scenarios, notice to the supplier | `disqualify`, `sourcing.bid.disqualified` | S2 same | MISSING | VERIFIED |
| T30 | Evaluator conflict-of-interest declaration; conflict bars scoring and the award proposal | `declare_conflict`, `_require_declaration` | S2 `scores_are_numbers_*` | MISSING (only the proposer's text at award) | VERIFIED |
| T31 | SOD-05 sole evaluator cannot award; approver is not the proposer | `sod.guard_and_record`, `_award_sod` | S2 `sod_05_the_sole_evaluator_cannot_propose_the_award` (new: the rule had no test), `award_needs_every_criterion*` | CODE ONLY | VERIFIED |
| T32 | TCO formula and units, every component | `sourcing_tco.compute` | S2 `tco_stack_always_adds_up`, `tco_components_*` | PARTIAL (no safety stock, no duty rule, no incoterm) | VERIFIED |
| T33 | TCO missing input is explicit ("incomplete"), never silently zero | `compute`, `bid_line.tco_incomplete/tco_trace` | S2 `missing_tco_inputs_are_flagged*` | WRONG (zero, reproduced) | VERIFIED |
| T34 | TCO breakdown reconciles with the total | `compute` (`rounding`) | S2 `tco_stack_always_adds_up` | WRONG (parts rounded separately) | VERIFIED |
| T35 | TCO parameters per event frozen; partial overrides complete | `sourcing_tco.snapshot/effective` | S2 `partial_tco_parameters_*` | WRONG (a missing key invalidated every bid at the close, reproduced) | VERIFIED |
| T36 | Should-cost by commodity: components, margin, index linkage | `should_cost.py`, `should_cost_model` | S2 `should_cost_inputs_are_validated*` | PARTIAL (one parametric die-casting model; no validation) | VERIFIED |
| T37 | Should-cost input validation (negative margin, missing key) | `should_cost.parametric` | S2 same | WRONG (negative margin accepted, KeyError 500, reproduced) | VERIFIED |
| T38 | Price benchmarks: last price, weighted average, market, peer, band | `should_cost.benchmark_band/baseline_price`, `price_benchmark` | S2 `baseline_methods_and_benchmark_band` | MISSING | VERIFIED |
| T39 | Baseline method chosen on the event and carried to M11 | `baseline_price`, `savings._negotiated` | S2 `baseline_methods*`, `savings_summary_has_a_sign*`; DSO | PARTIAL (last price only) | VERIFIED |
| T40 | Negotiated savings = (baseline - awarded price) x annual quantity; a cost increase is not a saving | `should_cost.savings_summary`, `savings._negotiated` | S2 `savings_summary_has_a_sign*` | WRONG (negative amount booked as NEGOTIATED) | VERIFIED |
| T41 | Award scenarios: lowest cost, best value, capacity constrained | `build_scenarios`, `_optimise`, `_AwardContext` | SIG, W1S, R34 | VERIFIED | VERIFIED |
| T42 | Manual split by percentage or quantity, per line; must add up to 100 | `custom_scenario` | S2 `manual_split_must_add_up*` | MISSING | VERIFIED |
| T43 | Constrained optimisation: min/max share, max suppliers, capacity (twin), risk caps | `_line_candidates` | W1S, R34 `capacity_constrained*` | VERIFIED | VERIFIED |
| T44 | Optimiser is exact (proved against enumeration) | `_optimise` | S2 `optimiser_matches_brute_force_*` (160 random cases) | CODE ONLY | VERIFIED |
| T45 | Optimiser numeric robustness (equal thirds of capacity) | `EPS` | S2 `equal_thirds_*` | WRONG (declared infeasible, reproduced) | VERIFIED |
| T46 | Minimum order quantity in the optimisation | `_line_candidates`, `bid_line.moq` | S2 `equal_thirds_*`, `brute_force_*` | MISSING | VERIFIED |
| T47 | Unverified capacity: flagged, or blocked by policy | `capacityVerified`, `unverifiedCapacity` | S2 `incomplete_tco_and_unverified_capacity*` | WRONG (treated as unlimited without a word) | VERIFIED |
| T48 | Risk score and savings per scenario | `award_scenario.risk_score`, `_scenario_risk` | S2 `manual_split_*` (risk), W1S | PARTIAL (savings only) | VERIFIED |
| T49 | Local content / ESG caps in the allocation | none (no data held) | - | MISSING | MISSING |
| T50 | Award approval by value band; clinical sign-off | `propose_award`, `rules.band_chain`, `ind_healthcare` | SIG, W1S, S2 `award_needs_every_criterion*` (authority stored) | VERIFIED | VERIFIED |
| T51 | Non-lowest award needs a written rationale (a sentence, not a word) | `award_gate` | S2 `award_needs_every_criterion*` | PARTIAL (any non-empty text) | VERIFIED |
| T52 | Award exceptions: limited competition, incomplete TCO, unverified capacity, cost increase need a rationale and approval | `award_gate`, `award_decision.exceptions` | S2 `limited_competition_*`, `incomplete_tco_*` | MISSING | VERIFIED |
| T53 | Award refused when a criterion is unscored, the gate is failed or pending, the bid is gone or expired | `award_gate` | S2 `award_needs_every_criterion*`, `technical_gate*` | WRONG (unscored counted as zero, reproduced) | VERIFIED |
| T54 | Lead time against the need date at publish and at award | `publish_checks`, `award_gate` | S2 `publish_guards_*`; award side CODE ONLY | MISSING | PARTIAL |
| T55 | Award outputs: contract draft per supplier, price validity, quota arrangement 60/40, savings initiative | `contract._from_award`, `_add_quota`, `savings` | SIG | VERIFIED | VERIFIED |
| T56 | Source list entry on contract activation | `sourcing_handoff._source_list` | S2 `signature_award_reads_back*` (reads); consumer exercised by SIG's activation | MISSING | VERIFIED |
| T57 | PO release eligibility per contract | `sourcing_analysis.handoff` | S2 `signature_award_reads_back*` | MISSING | VERIFIED |
| T58 | Regret letters without competitor data; notice to a disqualified bidder | `_regret_letters`, `sourcing_notify` | S2 `award_sends_regret_letters*`, R34 `award_and_consumption_*` | PARTIAL (generic "awarded elsewhere") | VERIFIED |
| T59 | Cancellation any time before the award; no cancellation after | `cancel` | R34, S2 `state_machine_refuses_illegal_commands*` | VERIFIED | VERIFIED |
| T60 | Re-tender / clone, templates | `sourcing_templates` | S2 `templates_and_clones_*` | MISSING | VERIFIED |
| T61 | Early access to bids blocked and logged: list, line matrix, comparison, CSV export | `bids_view`, `comparison`, `export_csv` | CTL, S2 `two_person_bid_opening*`, `comparison_and_csv_export*` | PARTIAL (list and line matrix only) | VERIFIED |
| T62 | Bid opening ceremony (two people) | `close`, `open_bids`, `bid_opening` | S2 `two_person_bid_opening*` | MISSING (BP silent: optional by policy) | VERIFIED |
| T63 | `bids.unsealed` audit event | `_unseal` (BIDS_UNSEALED), outbox `sourcing.bids.unsealed` | S2 `two_person_bid_opening*` | VERIFIED (audit) | VERIFIED |
| T64 | Draft to Published guards: P01 purpose code, mandatory fields, budget soft/hard stop, open hours | `publish_checks`, `category_budget_check` | S2 `publish_guards_*`, `category_budget_*` | MISSING | VERIFIED |
| T65 | Published as a state (scheduled opening) | `open_at`, `SOURCING_OPEN` timer | S2 `scheduled_opening_*` | WRONG (published and opened in one step; Published unreachable) | VERIFIED |
| T66 | Minimum bidders / competitive flag | `min_bidders`, `competitive` | S2 `limited_competition_*`, `two_person_bid_opening*` | MISSING | VERIFIED |
| T67 | State machine: illegal transitions answer 409 | `SM`, `publish` guard | S2 `state_machine_refuses_illegal_commands*` | VERIFIED | VERIFIED |
| T68 | ABAC on category, plant, company code at create / publish / close / open / disqualify / award / export | `abac` actions `SOURCING_*`, `AWARD_APPROVE` | CODE ONLY (policy evaluation covered by existing ABAC tests) | PARTIAL (award only) | CODE ONLY |
| T69 | RLS and grants on the new tables | migration 0022 | migration check (up, down, up, `alembic check`) | n/a | VERIFIED |
| T70 | Idempotency-Key and If-Match / ETag on commands | `_command`, `_event`, `get_event` ETag | S2 `api_etag_stale_write_*` | PARTIAL (create and cancel) | VERIFIED |
| T71 | Time handling: deadlines without a zone are IST | `sourcing.aware` | S2 `naive_deadlines_*` | WRONG (TypeError, reproduced) | VERIFIED |
| T72 | Supplier view hides internals | `get_event` | S2 `api_etag_stale_write_supplier_view*` | PARTIAL (bundle with requisition numbers visible) | VERIFIED |
| T73 | Comparison matrix export with hash, audited | `export_csv` | S2 `comparison_and_csv_export*` | MISSING | VERIFIED |
| T74 | Outlier / abnormally low bid screen (statistics and should-cost) | `detect_outliers` | S2 `outlier_and_collusion_screens*` | MISSING | VERIFIED |
| T75 | Collusion hints from data PIC holds | `collusion_hints` | S2 same | MISSING | VERIFIED |
| T76 | Pipeline and event history | `pipeline`, `history` | S2 `signature_award_reads_back*` | MISSING | VERIFIED |
| T77 | KPIs: cycle time, competitive events %, negotiated savings %, bidders per event | `sourcing_kpi.py` | S2 `m05_kpis_are_defined*` | WRONG (three of four measured something else) | VERIFIED |
| T78 | KPIs: participation, award-to-contract, savings link, non-lowest awards | `sourcing_kpi.py` | S2 same | MISSING | VERIFIED |
| T79 | Events: published, awarded, bid.submitted, cancelled + bids.unsealed, bid.withdrawn, bid.disqualified, award.regret with schemas | `events/schemas`, catalogue | `test_wave1_jobs` catalogue tests | PARTIAL | VERIFIED |
| T80 | Digital-twin capacity limits the allocation (RFQ-2231: 60k, 60/40) | `_line_row`, `_line_candidates` | SIG | VERIFIED | VERIFIED |
| T81 | Signature case numbers 412/398/405, should-cost 391, baseline 410, weighted 400.8 | seed `axion.py` | SIG, S2 `signature_award_reads_back*` | VERIFIED | VERIFIED |
| T82 | Source determination 9.2 with quota counters | `source.determine` | SOP | VERIFIED | VERIFIED |

Counts (82 rows): see section 3.

## 3. Counts

| Status | Before this pass | After |
|---|---|---|
| VERIFIED | 17 | 75 |
| CODE ONLY | 2 | 1 |
| PARTIAL | 15 | 2 |
| MISSING | 29 | 4 |
| WRONG | 18 | 0 |
| n/a | 1 | 0 |
| Rows | 82 | 82 |

Still MISSING: Dutch and sealed-then-auction (T05), alternate offers (T19), two-envelope evaluation (T28), local content / ESG caps in the allocation (T49).
Not fully proved by a test: T18 (automatic offer expiry; the check at the award is built), T54 (award-side lead-time check), T68 (ABAC on the new sourcing actions: registered, not exercised with a restricted user).

## 4. Defects found and fixed

"Reproduced" = the probe ran against the original code (HEAD b129437) and showed the failure; "read" = found by reading the original code, the new test
asserts the correct behaviour. Regression tests are in `test_sourcing_second_pass.py`.

| ID | Defect and evidence | Fix | Test |
|---|---|---|---|
| R1 | A close time sent without a zone (the API model accepts one) was compared with the aware clock: `publish` raised `TypeError: can't compare offset-naive and offset-aware datetimes` (reproduced) | `sourcing.aware()` reads a naive deadline as IST in `create_event`, `new_round`, the clarification deadline and the opening time | `naive_deadlines_are_read_as_ist_*` |
| R2 | A refused bid (late, uninvited, blocked) left no audit entry; only the early read was logged (reproduced: audit of an uninvited bid = CREATED, PUBLISH, OPEN) | `_bid_gate` + `log_refusal` write `LATE_BID_REFUSED`, `UNINVITED_BID_REFUSED`, `INELIGIBLE_BID_REFUSED`, `DISQUALIFIED_BID_REFUSED`, `BID_ACCESS_DENIED` in their own transaction (falls back to the caller's session when the audit-chain lock is held, never deadlocks) | `late_uninvited_ineligible_and_early_attempts_are_logged` |
| R3 | `int(price * 100)` truncated a unit price to paise: 398.456 became 39845 and tied with 398.454 (reproduced: both 39845) | half-up rounding at the opening; quoted price kept | `prices_round_half_up_when_the_bid_is_opened` |
| R4 | `Infinity` (and NaN) passed submission validation; at the close the line was dropped and the bid became INVALID with no notice to the supplier (reproduced) | `_finite()` on every number of a bid line | `bid_lines_refuse_nonfinite_implausible_and_inconsistent_values` |
| R5 | A unit price 100 times the baseline (a misplaced decimal point) was accepted and ranked (reproduced) | `SOURCING-POLICY.priceBand` (0.05 to 20 times the baseline, absolute limit), also for auction bids | same, `auction_soft_close_*` |
| R6 | When the twin had no PPM the quality cost was zero with no flag: KD002 TCO 39,981 with quality 0 (reproduced) | `tco_incomplete`, `MISSING` component, scorecard fallback, policy REJECT; award needs a rationale | `missing_tco_inputs_are_flagged_never_silently_zero` |
| R7 | Equal total cost was ranked in the order the database returned the bids (reproduced) | tie-break weighted score, earlier submission, supplier code; `rank`, `tiedWithPrevious` | `equal_total_cost_is_ranked_by_score_then_time_then_code` |
| R8 | The TCO components were rounded one by one while the total was rounded from the exact sum, so the stack could differ from the total by paise (read) | the total is still the rounded exact sum (numbers of running events do not move); `rounding` is shown so the stack adds up | `tco_stack_always_adds_up_to_the_total` (200 random inputs) |
| R9 | Three suppliers each able to supply a third (capacity 30,000 of 90,000) were declared infeasible because the thirds sum to 0.9999...9 (reproduced: no allocation) | tolerance `EPS`, the residue goes to the cheapest supplier so shares add up to exactly 1 | `equal_thirds_of_capacity_are_feasible_and_moq_is_respected` |
| R10 | The service accepted an evaluator score of 150 (only the API model bounded it) (reproduced) | 0 to 100 and finite checked in `score` | `scores_are_numbers_from_0_to_100_and_evaluators_declare_first` |
| R11 | No technical gate and no way to take a bidder out of the evaluation (read) | `Criterion.min_score`, `disqualify`, stale-scenario marking, re-entry refused | `technical_gate_and_disqualification_keep_a_bidder_out_of_the_award` |
| R12 | An award went ahead with a manual criterion nobody scored: it counted as 0 and the event moved to Award Pending (reproduced) | `requireAllCriteriaScored` blocks it (`UNSCORED_CRITERIA`); the matrix lists `unscored` | `award_needs_every_criterion_scored_*` |
| R13 | An award on limited competition, an incomplete TCO, unverified capacity or a cost increase needed no rationale and, below the threshold, no approver (read) | `award_gate` exceptions; rationale of at least `minRationaleChars`; such an award always goes to the approvers; recorded on the decision. The incomplete-TCO and unverified-capacity exceptions are always recorded but need the rationale only when `incompleteTcoNeedsRationale` / `unverifiedCapacityNeedsRationale` are on (off by default: the existing AXN packs award on suppliers without PPM or capacity data; the KAC rule version turns both on) | `limited_competition_*`, `incomplete_tco_and_unverified_capacity_*`, `award_needs_every_criterion_*` |
| R14 | An award above the baseline was booked as a negative NEGOTIATED ledger entry (read: `savings._negotiated`) | booked as 0, the audit trail records `costIncreaseMinor`, the award needs a rationale | `savings_summary_has_a_sign_*` |
| R15 | The supplier's event view carried the buyer's `bundle` (requisition numbers, category plan) and, after this pass, would have carried the budget and rule versions (read) | the supplier view drops them | `api_etag_stale_write_supplier_view_*` |
| R16 | Should-cost accepted a negative margin (a price below cost: 160.50 on a 340 cost, reproduced) and crashed with `KeyError` (500) on a missing input (reproduced) | validated inputs, margin 0-100, 422 `SHOULDCOST_INVALID` | `should_cost_inputs_are_validated_*` |
| R17 | Three of the four BP KPIs measured something else: cycle time ended at the creation of the award proposal (6.1 days on the signature data instead of the approved award), competitive events looked at statuses no event has and counted withdrawn and invalid bids, bidders per event counted bid rows (reproduced values) | re-defined in `sourcing_kpi.py` (the codes, targets and history stay) | `m05_kpis_are_defined_and_measure_*` |
| R18 | The auction soft close could be extended without limit, and an auction bid had no plausibility check or ceiling (reproduced: 30 bids inside the trigger window gave 30 extensions and moved the end by 150 minutes) | `maxExtensions`, `ceilingMinor`, price band | `auction_soft_close_stops_extending_after_the_cap_*` |
| R19 | The same supplier twice in the invitees raised `IntegrityError` (500) (reproduced) | `DUPLICATE_INVITEE` 422 | `event_definition_checks` |
| R20 | A TCO override without every rate (for example only the carrying rate) raised `KeyError` for every line at the close; the lines were skipped and every bid became INVALID without a word (reproduced: unsealed 0) | the snapshot completes missing values from the rule; unknown keys refused | `partial_tco_parameters_do_not_break_the_close` |
| R21 | The service accepted any event type (RFX) and criteria without validation (duplicate codes, negative or fractional weights, 99.9 became 99) (reproduced for the type; read for the rest) | validated | `event_definition_checks` |
| R22 | A requirement line of another category was sourced under the event's category without a trace (read) | audited (`categoryMismatch`) by default, refused when `lineCategoryCheck = ENFORCE`; bundles always refuse | `event_definition_checks` |
| R24 | Sealed bids that the configured `PIC_FIELD_KEY` cannot open (cryptography `InvalidToken`) ended in a bare 500 at the close (read) | `503 FIELD_KEY_MISMATCH` naming PIC_FIELD_KEY, no ciphertext, audited once per event (the shape of `finance_controls.supplier_gstin`) | `sealed_bids_that_the_field_key_cannot_open_*` |
| R23 | `Published` was unreachable as a state: publish moved straight to Open (read) | scheduled opening (`open_at`, `SOURCING_OPEN` timer) | `scheduled_opening_makes_published_a_resting_state` |

## 5. Calculations and checks added

* **TCO engine** (`sourcing_tco.py`, rule set `SOURCING-TCO`): every component with value, status, formula and inputs; freight estimated from the incoterm,
  duty from the HS-prefix rate table, GST stripped, price per base unit, currency at the event's reference date, carrying cost over lead time **plus the days the
  safety stock lasts**, quality cost from PPM (twin, then scorecards, then rule default, else MISSING), payment-term value; `incomplete` flag; an event keeps a
  copy of the parameters, and an event made before the rule set keeps the original formula and numbers.
* **Bid normalisation and comparison** (`sourcing_analysis.comparison`): TCO stack with trace, should-cost delta, benchmark band, price score by method,
  technical gate, ranking with tie-break, excluded bids with reasons; CSV export with SHA-256, audited, only after the opening.
* **Screens**: abnormally low / high bids (median, z-score, should-cost), collusion hints (identical totals, identical line pattern, shared PAN / GSTIN /
  bank account / parent / contact e-mail / address). PIC holds no IP address or director data, so those are listed as not checked.
* **Should-cost and benchmarks** (`should_cost.py`): data-driven commodity models with index linkage, five baseline methods, benchmark band, savings summary with sign.
* **Award optimisation**: MOQ, unverified-capacity policy, numeric tolerance, proved exact against enumeration; manual split by percentage or quantity per
  line; risk score per scenario.
* **Award governance**: authority band stored, exceptions with mandatory rationale, evaluator conflict declarations, technical gate, disqualification, two-person
  opening, regret letters, offer validity, lead time against the need date.
* **Lifecycle checks**: P01 purpose code, mandatory fields per type, minimum open hours, clarification deadline, close before the need date, budget soft/hard
  stop with justification, minimum bidders and the competitive flag, scheduled opening.
* **Governance of change**: new rule sets `SOURCING-POLICY` and `SOURCING-TCO` (validated by `POST /v1/admin/rules`, seeded for every tenant by migration 0022).
* **Pipeline and KPIs**: cockpit by stage, event history, eight M05 KPIs. **Templates and cloning.**

## 6. Datasets (pack `sourcing_ops`, D17, all MOCK-labelled)

Built through the real services with the business clock pinned; see `backend/data/erp_mock/KAC_SOURCING/README.md` for each dataset, the formulas, the
deliberately wrong cases and how to regenerate (`python -m app.pic.tools.sourcing_mock --check`).

| | KAC (first client) | AXN (signature tenant; non-signature events only) |
|---|---|---|
| Events | 40, created 14 Apr 2025 - 31 Oct 2026: RFQ 29, RFP 5, RFI 3, reverse auction 3; multi-round 2, lot bidding 2 | 6 in Aug-Sep 2027: RFI, RFP, multi-round RFQ, lot RFQ, cancelled RFQ, two-person opening |
| States | AWARDED 19, CANCELLED 4, UNDER_EVALUATION 4, AWARD_PENDING 3, OPEN 3, CLOSED 2 (awaiting the two-person opening), PUBLISHED 2 (scheduled opening), DRAFT 3 | AWARDED 3, CANCELLED 1, CLOSED 1, UNDER_EVALUATION 1 |
| Bids | 135 sealed bids (3-7 per event) and 26 auction bids | in the same range |
| Other | 5 clarifications, 23 award decisions, 22 contracts born from awards (`SA-55nn`, suppliers with no `KAC-*` contract; 5 active with published prices), 4 quota arrangements, 5 source-list entries, 34 savings initiatives (LAST_PRICE, WEIGHTED_AVG, SHOULD_COST, MARKET_INDEX, BUDGET baselines), 10 should-cost models, 190 index values (10 indices x 19 months), 80 benchmarks, 3 templates (1 clone, 1 from a template), 122 twin snapshots, 121 supplier bidder logins, 38 requisitions | 5 twin snapshots, 8 bidder logins, 12 benchmarks |
| Service-driven calls | 604 | 71-76 |
| Local run time | 143-225 s | 24-31 s |

Deliberately wrong cases: K03 late bid refused and logged, uninvited supplier, withdrawn and re-bid, replaced bid; K24 and K27 early read refused; K15, K24, K25
two-person opening with 2, 0 and 1 openers; K11 USD import where the HS 8479 line has no duty rate (incomplete TCO); K10 technical-gate failure and
disqualification; K05, K18, K36 non-lowest awards with rationale; K39 two valid bids against a minimum of three (limited competition); K06 capacity-constrained dual
source; K12 two auction extensions; K34-K37 cancellations at draft, after bids, at award pending and while open. The history before 1 April 2026 needs rule versions
(the tenants' rules are effective from 1 April 2026): the pack publishes 64 `-HIST-MOCK` copies for KAC and says so in its README.

## 7. Behaviour changes other code can depend on

* `sourcing.submit_bid(..., valid_until=None)`; the sealed payload keeps only known fields; `Bid.status` gains WITHDRAWN and DISQUALIFIED; the unit price is rounded half-up.
* `sourcing.score` needs a prior `declare_conflict` (the Axion seed and `datasets/branches.py` now declare before they score; `test_review_f3_f4` and
  `test_wave1_sourcing_contracts` were adjusted: a declaration in one test, the requirement's purpose code in the shared helper).
* `sourcing.publish` is stricter (P01, mandatory `need_date` for RFQ / RFP / auction, RFQ and auction need a PRICE_TCO weight, budget check, open hours); `propose_award` is stricter (see R12, R13).
* `create_event` takes `scoring_method`, `reference_date`, `clarification_close_at`, `open_at`, `budget_justification`, `min_bidders`, `should_cost_model`,
  `template_code`, `cloned_from`; `tco_params` is stored as the full snapshot (camelCase keys, `_v: 2`); the three snake_case keys are still accepted.
* `evaluation_matrix` rows gain `rank`, `tiedWithPrevious`, `priceScore`, `unscored`, `technicalGate`, `tcoIncomplete`, `tcoMissing`, `capacityVerified`, `submittedAt`, `validUntil`.
* The `sourcing.event.awarded` payload gains `baselineMethod`, `savings`, `scenario`, `exceptions`, `needDate`, `regretSupplierIds`.
* `contract.activated` writes a source-list entry for the awarded supplier and material (TD 9.2), so source-list counts in tests that include an awarded event are higher.
* `savings._negotiated` books 0 (not a negative amount) for a cost increase. `contract.activated` also writes a source-list entry. The four BP M05 KPIs are
  re-defined (same codes). A bidder that is not awarded receives the regret letter instead of the generic notice (same kind and dedup key).
* New ABAC actions SOURCING_CREATE / SOURCING_MANAGE / SOURCING_EXPORT (users without the attributes are unrestricted, as before).

## 8. What remains, and why

* Dutch and sealed-then-auction formats, alternate offers, two-envelope evaluation (technical before price), local-content and ESG caps in the allocation: not
  specified in enough detail, or no data held.
* Automatic expiry of an offer when its validity ends (enforced at the award today); the award-side lead-time check and the ABAC actions are code-only.
* Evaluator weights and panels (scores are averaged equally); event approval before publication (the BP has none).
* The frontend: no screen was changed (see section 10).

## 9. What the product owner must supply

* `SOURCING-POLICY` values: minimum bidders per event type, minimum open hours, whether bids are always opened by two people, minimum rationale length, lead-time
  and category checks (ENFORCE or WARN), plausibility band. `SOURCING-TCO` values: carrying rate, cost of capital, cost of poor quality per defect (by category),
  freight estimates by incoterm, **customs-duty rates by HS code**, which incoterms the buyer pays for.
* Category plan budgets per fiscal year (the budget check is "not applicable" without them) and the award approval bands and delegation.
* Index feeds (LME aluminium, steel, copper, polymers, rubber, paper, diesel) and market / peer price data for the benchmarks; should-cost model parameters per
  commodity confirmed by the costing team (the MOCK models are illustrations).
* Twin data: PPM, lead time and free capacity with an evidence level for the suppliers that bid; a rule on which evidence level counts as verified capacity.
* Replace every MOCK value of the pack (README lists them) before any figure is shown to a client as real.

## 10. Screens and API for the frontend pass

Routes added: `POST /v1/sourcing/events/{ref}/bids/withdraw`, `/open`, `/declarations`, `/disqualify`, `/scenarios/custom`, `/clone`; `GET .../comparison`,
`.../comparison.csv`, `.../evaluators`, `.../handoff`, `.../history`; `GET /v1/sourcing/pipeline`; `GET/POST /v1/sourcing/templates`, `POST /v1/sourcing/templates/{code}/events`;
`GET/POST /v1/sourcing/should-cost/models`, `POST /v1/sourcing/should-cost/evaluate`; `GET/POST /v1/sourcing/benchmarks`; `POST /v1/sourcing/tco/simulate`.
Changed: `POST /v1/sourcing/events` (new fields), `POST .../bids` (currency, incoterm, origin, MOQ, UoM factor, tax, HS code, `valid_until`; freight / duty /
packaging are nullable), `GET /v1/sourcing/events/{ref}` (ETag; send `If-Match` on commands; `policy` with the limits and award rules, internal users only), `GET .../comparison` (`tcoTrace` per bid line: value, status, formula, inputs), `POST /v1/sourcing/templates/{code}/events` (also `open_at`, `clarification_close_at`, `reference_date`, `min_bidders`, `budget_justification`, `should_cost_model`, `baseline_method`, `baseline_price_minor`), `PUT .../auction` (`ceilingMinor`).
Screens: SRC-01 cockpit (pipeline), SRC-02 builder (scoring method, gate, schedule, budget justification, templates), SRC-03 comparison (TCO trace, flags,
screens, export), SRC-04 studio (manual split, risk score), SRC-05 approval (exceptions, authority), supplier portal (withdraw, currency, validity), opening ceremony.

## 11. How the proof was run

```
cd backend
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:54329/<fresh db> venv\Scripts\python.exe -m pytest tests/pic/test_sourcing_second_pass.py \
  tests/pic/test_signature_case.py tests/pic/test_review_f3_f4.py tests/pic/test_wave1_sourcing_contracts.py tests/pic/test_source_ops.py tests/pic/test_controls.py
TEST_DATABASE_URL=... venv\Scripts\python.exe -m pytest tests/pic/test_datasets_sourcing_ops.py tests/pic/test_datasets_contracts_kac.py   # dataset tests run last
venv\Scripts\python.exe -m app.pic.tools.sourcing_mock --check
```
Results of the runs are in the hand-over report of this pass. The probes against the original code are `probe_old.py` (scratch, not committed): the rows marked
"reproduced" above come from its output.
