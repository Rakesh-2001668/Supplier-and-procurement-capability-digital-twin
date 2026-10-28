// NFR thresholds (Technical Document §15):
//   transactional APIs   P95 < 400 ms
//   spend cube/overview  P95 < 3 s
//   error rate           < 1 %
// Each NFR is enforced globally per request kind and again per scenario (k6 tags every request with
// its scenario name). A second, looser threshold per metric aborts the run early (abortOnFail) when
// the system is grossly failing, so a broken staging deployment does not get hammered for the full run.
import { KIND } from './http.js';

export const NFR = {
  transactionalP95Ms: 400,
  spendP95Ms: 3000,
  errorRate: 0.01,
};

const BUDGET = {
  [KIND.transactional]: NFR.transactionalP95Ms,
  [KIND.auth]: NFR.transactionalP95Ms,
  [KIND.spend]: NFR.spendP95Ms,
};

const ABORT_AFTER = __ENV.ABORT_EVAL_DELAY || '1m';

function gross(threshold) {
  return { threshold, abortOnFail: true, delayAbortEval: ABORT_AFTER };
}

// scenarios: [{ name, kinds: [KIND.*] }]
export function nfrThresholds(scenarios) {
  const kinds = {};
  scenarios.forEach((s) => s.kinds.forEach((k) => (kinds[k] = true)));

  const t = {
    http_req_failed: [`rate<${NFR.errorRate}`, gross('rate<0.10')],
    checks: ['rate>0.99', gross('rate>0.90')],
    // Any 429 means the staging rate limits were not raised for the test (see README).
    pic_rate_limited: ['count<1'],
  };
  Object.keys(kinds).forEach((kind) => {
    const budget = BUDGET[kind];
    t[`http_req_duration{kind:${kind}}`] = [`p(95)<${budget}`, gross(`p(95)<${budget * 5}`)];
  });
  scenarios.forEach((s) => {
    t[`http_req_failed{scenario:${s.name}}`] = [`rate<${NFR.errorRate}`];
    t[`checks{scenario:${s.name}}`] = ['rate>0.99'];
    s.kinds.forEach((kind) => {
      t[`http_req_duration{scenario:${s.name},kind:${kind}}`] = [`p(95)<${BUDGET[kind]}`];
    });
  });
  return t;
}

export const summaryTrendStats = ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max', 'count'];
