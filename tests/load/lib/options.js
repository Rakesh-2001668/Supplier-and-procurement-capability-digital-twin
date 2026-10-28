// Scenario profiles and option builders.
import { config } from './config.js';
import { KIND } from './http.js';
import { nfrThresholds, summaryTrendStats } from './thresholds.js';

// Baseline peak-hour mix for one tenant (iterations per minute), scaled by LOAD_FACTOR in all.js.
// requestsPerIteration is approximate and only feeds the rate-limit pre-flight warning.
export const PROFILES = {
  signin: { ratePerMin: 12, preAllocatedVUs: 2, maxVUs: 10, requestsPerIteration: 2, kinds: [KIND.auth, KIND.transactional] },
  worklists: { ratePerMin: 300, preAllocatedVUs: 30, maxVUs: 150, requestsPerIteration: 9, kinds: [KIND.transactional] },
  po_detail: { ratePerMin: 180, preAllocatedVUs: 10, maxVUs: 60, requestsPerIteration: 2, kinds: [KIND.transactional] },
  requisition_create_submit: { ratePerMin: 60, preAllocatedVUs: 10, maxVUs: 60, requestsPerIteration: 2, kinds: [KIND.transactional] },
  invoice_match: { ratePerMin: 30, preAllocatedVUs: 5, maxVUs: 40, requestsPerIteration: 1.3, kinds: [KIND.transactional] },
  spend_overview: { ratePerMin: 12, preAllocatedVUs: 5, maxVUs: 30, requestsPerIteration: 7, kinds: [KIND.spend] },
};

function vus(profile, factor) {
  return {
    preAllocatedVUs: config.preAllocatedVUs || Math.max(1, Math.ceil(profile.preAllocatedVUs * factor)),
    maxVUs: config.maxVUs || Math.max(2, Math.ceil(profile.maxVUs * factor)),
  };
}

// Ramp up, hold, ramp down on an open (arrival-rate) model: new iterations start at the target rate
// whatever the response times are, so a slow API shows up as latency and dropped_iterations instead
// of silently lowering the load.
export function rampingArrival(profile, ratePerMin, factor, extra) {
  return Object.assign(
    {
      executor: 'ramping-arrival-rate',
      startRate: 0,
      timeUnit: '1m',
      stages: [
        { target: ratePerMin, duration: config.rampUp },
        { target: ratePerMin, duration: config.duration },
        { target: 0, duration: config.rampDown },
      ],
    },
    vus(profile, factor),
    extra || {},
  );
}

export function constantArrival(profile, ratePerMin, factor, extra) {
  return Object.assign(
    { executor: 'constant-arrival-rate', rate: ratePerMin, timeUnit: '1m', duration: config.duration },
    vus(profile, factor),
    extra || {},
  );
}

export function smokeScenario(extra) {
  return Object.assign({ executor: 'shared-iterations', vus: 1, iterations: 1, maxDuration: '2m' }, extra || {});
}

export function commonOptions(scenarios, thresholdScenarios) {
  return {
    scenarios,
    thresholds: nfrThresholds(thresholdScenarios),
    summaryTrendStats,
    setupTimeout: '3m',
    teardownTimeout: '1m',
    tags: { suite: 'pic-load', target: config.baseUrl.replace(/^https?:\/\//, '') },
    userAgent: 'pic-k6-load/1.0',
  };
}

// Options for a standalone script: one named scenario so its tags match the per-scenario thresholds.
// SMOKE=1 runs one iteration on one VU (for checking a script against staging before a real run).
export function standaloneOptions(name) {
  const profile = PROFILES[name];
  const rate = config.ratePerMin || profile.ratePerMin;
  const scenario = config.smoke ? smokeScenario() : rampingArrival(profile, rate, 1);
  return commonOptions({ [name]: scenario }, [{ name, kinds: profile.kinds }]);
}

export function expectedRequestsPerMinute(names, factor) {
  if (config.smoke) return 0;
  return names.reduce((sum, n) => {
    const p = PROFILES[n];
    const rate = names.length === 1 && config.ratePerMin ? config.ratePerMin : p.ratePerMin * (factor || 1);
    return sum + rate * p.requestsPerIteration;
  }, 0);
}
