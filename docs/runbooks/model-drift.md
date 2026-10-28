# Model drift and agent misbehaviour

**Scope:** the PIC agents (AIX-03: touchless PO, PO validation/risk, invoice exception explanation, classification, forecasting,
supplier risk, copilot) and the scores they use (`model_version` on agents and twins, e.g. `eta-v3`).

**Signals:**
- Agent acceptance rate below `agent.min_acceptance_rate` (agent console: accepted vs rejected recommendations;
  `GET /v1/agents/{code}/runs`).
- `pic_slo_touchless_ratio` or `pic_slo_first_pass_match_ratio` moving by more than ~10 points week over week without a policy
  change (check rule versions first: Administration → Rules).
- Users rejecting classification / forecasts; supplier late-delivery probability out of line with actual receipts.

## Contain first (minutes)

1. **Kill switch:** Administration → Agents, or `PUT /v1/agents/{code}/kill-switch {"on": true, "reason": "..."}`. The agent stops
   acting; the business process falls back to the human path (e.g. POs route for approval instead of releasing touchless). Audited.
2. Or lower autonomy (`PUT /v1/agents/{code}/autonomy`, e.g. L4 → L2 "recommend only") or its value limit.
3. Check whether any executed action needs reversal: `agent_run` rows with `action_taken = EXECUTED` since the drift started
   (`GET /v1/agents/{code}/runs`). Released POs can be changed or cancelled through the normal PO change process.

## Diagnose

- Data drift: compare input distributions in `agent_run.inputs` (e.g. `lateProb`, `valueMinor`, supplier status) for the last
  7 days vs the previous 30.
- Policy drift: a new rule version (DMN-02 / PO-RISK thresholds) changes outcomes legitimately — simulate it (ADM-03) with
  typical inputs and compare versions.
- Model version change: `model_version` on the agent and in `agent_run`; roll back to the previous version if the change
  coincides.
- Upstream data: master data or ERP import issues (wrong lead times, missing receipts) look like model drift.

## Recover

Fix data or roll back the model version; run the agent on a sample (`POST /v1/agents/{code}/runs` for on-demand agents) and
review the recommendations with the business owner; lift the kill switch with a reason. Record the incident in the agent's
change log (model risk register).
