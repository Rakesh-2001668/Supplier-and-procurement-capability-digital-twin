// Sign-in helpers.
//
// The API blocks a client IP for 5 minutes after 10 FAILED sign-ins (platform/http.py), so scripts
// sign in once per pooled user in setup() and share the tokens with every VU. Only the dedicated
// signin scenario signs in per iteration, and always with valid credentials. setup() stops at the
// first failed sign-in so a wrong PASSWORD costs one failed attempt, not one per user.
import exec from 'k6/execution';
import { config } from './config.js';
import { json, KIND, request } from './http.js';

export const TOKEN_PATH = '/v1/auth/token';

// Returns { token } or { error } (never throws; never logs the password).
export function signIn(email, kind, tags) {
  if (!config.password) return { error: 'PASSWORD is not set (the seeded users\' shared password on staging)' };
  const res = request('POST', TOKEN_PATH, {
    body: { tenant: config.tenant, email, password: config.password },
    name: `POST ${TOKEN_PATH}`,
    kind: kind || KIND.setup,
    expected: [200],
    tags,
  });
  const body = json(res);
  if (res.status !== 200 || !body) {
    const code = body && body.code ? body.code : `HTTP ${res.status}`;
    return { error: `sign-in failed for ${email}: ${code}${body && body.traceId ? ` (traceId ${body.traceId})` : ''}` };
  }
  if (body.mfaRequired) {
    return { error: `${email} has an MFA authenticator; use a load-test user without MFA (see README, "Users")` };
  }
  if (!body.access_token) return { error: `sign-in for ${email} returned no access_token` };
  return { token: body.access_token };
}

// setup(): sign in each user of the requested pools once. Aborts on the first failure.
export function signInPools(roles) {
  const sessions = {};
  roles.forEach((role) => {
    const emails = config.users[role];
    if (!emails || emails.length === 0) exec.test.abort(`no users configured for role "${role}"`);
    sessions[role] = emails.map((email) => {
      const result = signIn(email, KIND.setup);
      if (result.error) exec.test.abort(`[setup] ${result.error}`);
      return { email, token: result.token };
    });
  });
  return sessions;
}

// Per-VU session: VU n uses user (n-1) mod poolSize, so load spreads evenly over the pool.
const vuSessions = {};

export function sessionFor(data, role) {
  if (!vuSessions[role]) {
    const pool = data.sessions[role];
    const pick = pool[(exec.vu.idInTest - 1) % pool.length];
    vuSessions[role] = { email: pick.email, token: pick.token };
  }
  return vuSessions[role];
}

// Authenticated request. A 401 (token expired during a long soak; default TTL 480 min) triggers one
// valid re-sign-in for this VU and a single retry.
export function call(session, method, path, opts) {
  const o = Object.assign({}, opts, { token: session.token });
  let res = request(method, path, o);
  if (res.status === 401) {
    const again = signIn(session.email, KIND.auth, { purpose: 'refresh' });
    if (again.token) {
      session.token = again.token;
      res = request(method, path, Object.assign({}, o, { token: again.token }));
    }
  }
  return res;
}
