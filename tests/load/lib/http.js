// HTTP helpers: JSON requests with tags, Idempotency-Key and X-Request-ID, status checks, and
// RFC 9457 problem+json reporting (code + traceId) on failure.
import http from 'k6/http';
import { check } from 'k6';
import crypto from 'k6/crypto';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';
import { config } from './config.js';

// Request kinds drive the NFR thresholds (lib/thresholds.js).
export const KIND = {
  transactional: 'transactional', // P95 < 400 ms
  spend: 'spend', // P95 < 3 s
  auth: 'auth', // sign-in, held to the transactional budget
  setup: 'setup', // setup()/discovery calls: excluded from latency NFRs
};

export const problemResponses = new Counter('pic_problem_responses');
export const rateLimited = new Counter('pic_rate_limited');

let errorLogs = 0;

export function uuidv4() {
  const b = new Uint8Array(crypto.randomBytes(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  let h = '';
  for (let i = 0; i < b.length; i++) h += (b[i] < 16 ? '0' : '') + b[i].toString(16);
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

// One key per logical command; reuse the same key only to test a deliberate replay.
export function idempotencyKey(prefix) {
  return `k6-${prefix || 'cmd'}-${uuidv4()}`;
}

export function json(res) {
  try {
    return res.json();
  } catch (e) {
    return null;
  }
}

function whereAmI() {
  try {
    return `${exec.scenario.name} vu=${exec.vu.idInTest} iter=${exec.scenario.iterationInTest}`;
  } catch (e) {
    return 'setup';
  }
}

function report(res, method, name, requestId) {
  const ctype = String((res.headers && (res.headers['Content-Type'] || res.headers['content-type'])) || '');
  const body = ctype.indexOf('json') !== -1 ? json(res) : null;
  const code = (body && body.code) || (res.status === 0 ? 'NETWORK' : `HTTP_${res.status}`);
  const traceId = (body && body.traceId) || (res.headers && res.headers['X-Request-Id']) || requestId;
  problemResponses.add(1, { code: String(code), name });
  if (res.status === 429) rateLimited.add(1, { name });
  if (errorLogs >= config.maxErrorLogsPerVu) return;
  errorLogs += 1;
  const detail = body && body.detail ? String(body.detail).slice(0, 300) : res.error || '';
  const retry = res.status === 429 && res.headers['Retry-After'] ? ` retryAfter=${res.headers['Retry-After']}s` : '';
  const problemJson = ctype.indexOf('application/problem+json') !== -1 ? '' : ` (content-type "${ctype}", not problem+json)`;
  console.warn(
    `[${whereAmI()}] ${name.indexOf(`${method} `) === 0 ? name : `${method} ${name}`} -> ${res.status} code=${code} traceId=${traceId}${retry} ${detail}${problemJson}`,
  );
}

// request(method, path, opts)
//   opts.token           bearer token
//   opts.body            object, sent as JSON
//   opts.name            metric name tag (templated path, e.g. "GET /v1/purchase-orders/{ref}")
//   opts.kind            KIND.* tag used by thresholds
//   opts.expected        accepted status codes (default [200])
//   opts.idempotencyKey  Idempotency-Key header for POST commands
//   opts.tags            extra tags
export function request(method, path, opts) {
  const o = opts || {};
  const expected = o.expected || [200];
  const name = o.name || `${method} ${path.split('?')[0]}`;
  const requestId = `k6-${uuidv4()}`; // the API echoes it as X-Request-ID and uses it as the problem traceId
  const headers = { Accept: 'application/json, application/problem+json', 'X-Request-ID': requestId };
  if (o.token) headers.Authorization = `Bearer ${o.token}`;
  if (o.idempotencyKey) headers['Idempotency-Key'] = o.idempotencyKey;
  let payload = null;
  if (o.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(o.body);
  }
  const tags = Object.assign({ name, kind: o.kind || KIND.transactional }, o.tags || {});
  const res = http.request(method, `${config.baseUrl}${path}`, payload, {
    headers,
    tags,
    timeout: config.requestTimeout,
    responseCallback: http.expectedStatuses.apply(null, expected),
  });
  const label = `${name} ${expected.join('|')}`;
  const ok = check(res, { [label]: (r) => expected.indexOf(r.status) !== -1 }, { kind: tags.kind });
  if (!ok) report(res, method, name, requestId);
  return res;
}

// Additional assertions on a response body; logs the traceId when one fails.
export function checkBody(res, name, assertions, kind) {
  const body = json(res);
  const named = {};
  Object.keys(assertions).forEach((k) => {
    named[`${name}: ${k}`] = () => {
      try {
        return Boolean(assertions[k](body));
      } catch (e) {
        return false;
      }
    };
  });
  const ok = check(res, named, { kind: kind || KIND.transactional });
  if (!ok && errorLogs < config.maxErrorLogsPerVu) {
    errorLogs += 1;
    const failed = Object.keys(assertions).filter((k) => !named[`${name}: ${k}`]());
    console.warn(`[${whereAmI()}] ${name}: body check failed (${failed.join(', ')}) traceId=${res.headers['X-Request-Id'] || '?'}`);
  }
  return body;
}
