// Combined peak-hour mix: every journey runs at the same time as its own k6 scenario on an open
// (arrival-rate) model, tagged scenario=<name>, with per-scenario and per-kind NFR thresholds.
// WRITES DATA (requisitions, invoices); staging only.
//
// Baseline rates (iterations/minute; LOAD_FACTOR multiplies all of them):
//   worklists                  300  ramping   buyer home screen, ~9 requests each
//   po_detail                  180  ramping   PO detail + schedule
//   requisition_create_submit   60  ramping   create + submit (+5 % idempotent replays)
//   invoice_match               30  constant  capture + match (+re-match of exceptions)
//   spend_overview              12  constant  overview, cube slices, treemap, suppliers, dashboard
//   signin                      12  constant  sign-in + /v1/me
// That is roughly 3,300 requests/minute at LOAD_FACTOR=1: raise the staging rate limits first (README).
//
//   k6 run -e BASE_URL=https://pic-staging.example.com -e PIC_LOAD_CONFIRM_STAGING=yes -e PASSWORD=... \
//          -e LOAD_FACTOR=1 -e DURATION=15m all.js
//   SMOKE=1 runs one iteration of every scenario (still writes one requisition and one invoice).
import { config } from './lib/config.js';
import {
  invoiceMatchFlow, poDetailFlow, requisitionFlow, setupFor, signinFlow, spendFlow, worklistsFlow,
} from './lib/flows.js';
import {
  commonOptions, constantArrival, expectedRequestsPerMinute, PROFILES, rampingArrival, smokeScenario,
} from './lib/options.js';

const F = config.loadFactor;
const rate = (name) => Math.max(1, Math.round(PROFILES[name].ratePerMin * F));

const RAMPING = ['worklists', 'po_detail', 'requisition_create_submit'];
const CONSTANT = ['invoice_match', 'spend_overview', 'signin'];
const EXEC = {
  worklists: 'worklists',
  po_detail: 'poDetail',
  requisition_create_submit: 'requisitionCreateSubmit',
  invoice_match: 'invoiceMatch',
  spend_overview: 'spendOverview',
  signin: 'signin',
};

const scenarios = {};
RAMPING.concat(CONSTANT).forEach((name) => {
  const extra = { exec: EXEC[name], tags: { journey: name } };
  if (config.smoke) scenarios[name] = smokeScenario(extra);
  else if (RAMPING.indexOf(name) !== -1) scenarios[name] = rampingArrival(PROFILES[name], rate(name), F, extra);
  // Constant scenarios start after the ramp-up so the steady state is measured with everything running;
  // they run for DURATION, inside the ramping scenarios' hold window.
  else scenarios[name] = constantArrival(PROFILES[name], rate(name), F, Object.assign(extra, { startTime: config.rampUp }));
});

export const options = commonOptions(
  scenarios,
  Object.keys(scenarios).map((name) => ({ name, kinds: PROFILES[name].kinds })),
);

export function setup() {
  return setupFor({
    roles: ['buyer', 'requester', 'ap', 'spend'],
    poNumbers: true,
    requisitionLine: true,
    invoiceTarget: true,
    expectedRequestsPerMinute: expectedRequestsPerMinute(Object.keys(PROFILES), F),
  });
}

export function worklists(data) {
  worklistsFlow(data);
}

export function poDetail(data) {
  poDetailFlow(data);
}

export function requisitionCreateSubmit(data) {
  requisitionFlow(data);
}

export function invoiceMatch(data) {
  invoiceMatchFlow(data);
}

export function spendOverview(data) {
  spendFlow(data);
}

export function signin() {
  signinFlow();
}
