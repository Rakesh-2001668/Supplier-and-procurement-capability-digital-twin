# PIC – Agent Run Analysis: Was the Parallel Agent Run Needed?

Date: 1 November 2026. Written for: the product owner, who asked whether the long agent run is worth its token cost.

## 1. Answer in one paragraph

The work the agents are doing is needed. The pending-workflow list (59 items) and the spec traceability matrix show real gaps against the Technical Document and Blueprint, and the agents have already produced a large amount of code for them. The way the run was organised is not needed and is wasteful. Eight agents edited one shared source tree at the same time, each one ran the full test suite (seeding alone takes about 11 minutes on this machine), and a browser tester ran against a dev server that those same edits kept recompiling. The result is a day of wall-clock time, hundreds of thousands of tokens per agent, and almost no verified output. I recommend stopping the parallel run, letting the code that is already written stand, and finishing with one integrated pass done by me.

## 2. What the run has produced so far (measured today)

| Measure | Value |
|---|---|
| Tracked files modified | 130 (+7,330 / −831 lines) |
| New untracked files | 218 (86 event schemas, 38 services, 15 platform, 10 tests, 7 migrations, 7 models, 5 API, frontend admin/industry screens) |
| Migrations written | 0008 to 0014, all seven, each still branching from 0007 and not yet chained |
| Local app | API :8080 and web :3000 both answering 200 |

So the build output is real and substantial. None of it has been verified together.

## 3. Status of each agent

| Agent | Scope | Status now | Verified? |
|---|---|---|---|
| A | Scheduled jobs, delegation, event consumers, agents | Stalled again (no progress for 10 minutes) | No report. One import bug in its file blocked 17 of C2's tests until fixed. |
| B | Procure-to-pay completion | Still running at last check | No report yet |
| C1 | Master data, suppliers, sourcing, contracts | Stalled again, mid-edit on two scan tests | No report |
| C2 | Spend cube, savings, KPIs, UI gaps | Reported, but with its own verification unfinished | Migration, type check and 8 unit tests pass. Full suite shows many failures it could not triage. Volume timings never produced. |
| D | Industry controls and MRP | Still running at last check | No report yet |
| E | Platform, security, workflow designer | Stalled again, mid-edit on CI gate | No report |
| F | ERP connectors, inbound sync, AI models | Resumed, still running at last check | No report yet |
| QA | Browser test of the live app | Reported, partial | Areas 4 to 8 not tested at all; areas 1 to 3 partly tested |

Token use is known only for the two that reported: C2 about 680,000 tokens and QA about 392,000 tokens. The other six have not reported usage. Their transcripts are each about 3 MB, similar to C2, so a rough planning figure is 0.5 to 0.7 million tokens each. That is an estimate, not a measurement.

## 4. Why it took a day and cost so much

1. **Shared tree, simultaneous edits.** Any agent running the suite sees failures caused by another agent's half-finished change. C2 reports "many failures" and cannot say which are its own. Every agent then spends tokens triaging noise.
2. **Eight full-suite runs on one machine.** Each run seeds the whole database (about 11 minutes alone) and the machine was memory-bound. That slowed everything, including the other agents.
3. **The browser tester was starved.** Pages took 12 s to over 300 s to load because the dev server recompiled on every builder edit. QA finished only part of area 2 and none of areas 4 to 8, after about 24 hours of wall time and 392,000 tokens.
4. **Stalls.** Five stalls of 10 minutes each (F, C2, A, C1, E) and several usage-limit cut-offs forced resumes, and each resume makes the agent re-read its files.
5. **Late discovery of cross-agent breaks.** Example: A's route bound the idempotency header to a path parameter named `key`, which stopped C2's API tests from importing. B's new control made the seed stop at Case 5 until C2 patched it. These are integration bugs that one integrated run would find once.

## 5. Is each part of the run still needed?

| Part | Needed? | Reason |
|---|---|---|
| Writing the missing workflow code (A, B, C1, C2, D, E, F) | Yes | The gaps are in the spec and the code does not exist otherwise. |
| Each agent running the full suite on its own database | No | Produces noise and load. One run after integration is enough. |
| Each agent doing volume or timing runs (C2 scale 0.05) | No, now | It had run for over an hour with no timings. Run it once, later, on a quiet machine. |
| Browser QA while builders are editing | No | The results are unreliable and the run is the most expensive per finding. Do it once after integration. |
| Resuming the three stalled agents (A, C1, E) | Not now | Their remaining work is smaller than the cost of another cold start. I can finish the loose ends during integration. |

## 6. Useful findings already banked

From the QA run (no severity 1 defects): quota shares shown as 0.6% instead of 60%; an ASN left "in transit" after a no-ASN receipt; the payment run dialog has no supplier or invoice filter although the API supports it; the Create PO dialog waits for every query to refetch before reporting success (so users may repeat the action); console 403s on two screens; a truncated spend tile; and two worker processes running, one with over 5,700 CPU seconds, which also explains part of the slowness. These go to the bug tracker.

From C2: the spend cube, savings pipeline and P&L, 61 KPI definitions, saved views, bulk task actions, accessibility fixes and migration 0011 are written and the migration round-trips cleanly.

## 7. Recommendation and next steps

1. Do not resume A, C1 or E for now.
2. Tell B, D and F to finish writing code only and report. No full-suite runs, no browser runs, no volume runs.
3. Stop the stray extra worker process on the local machine so the suite and dev server run at normal speed.
4. I integrate once: chain migrations 0008 to 0014, fix the import and seed conflicts, finish A, C1 and E's loose ends by reading their files, then run the full backend suite once, tsc, eslint and the build.
5. Re-run the browser QA once on the integrated build, one browser at a time, using the order in the QA report.
6. Then update the documents, push, and apply the new migrations to Neon only with your go-ahead.

Expected effect: the integrated pass is sequential and quiet, so the test and browser steps run at normal speed. I cannot promise a time. The tokens saved come from not paying six more cold starts and eight more suite triages.

## 8. What I need from you

Nothing blocks this. The one decision is below, and I am taking it as the default unless you say otherwise.

- **Decision (default taken):** trim the run as in section 7 instead of letting all agents finish their own verification. The alternative is to let every agent finish; it costs more and still ends with the same integration pass.
