// Production guard. Runs in the init context (imported by lib/config.js), so k6 stops before any VU
// starts, and again in setup() as a second line of defence (e.g. if a script is edited).
//
// The test refuses to run when:
//   * BASE_URL is missing or not http(s)://
//   * BASE_URL contains "neon.tech" (someone pasted a database host instead of the staging API)
//   * the BASE_URL host matches an entry of PIC_PRODUCTION_HOSTS (comma-separated; an entry matches the
//     host exactly, host:port exactly, or any sub-domain of it, e.g. "pic.alphahelion.io")
//   * PIC_LOAD_CONFIRM_STAGING is not exactly "yes"
import exec from 'k6/execution';

function hostOf(url) {
  const m = /^https?:\/\/(?:[^@/]*@)?(\[[^\]]+\]|[^:/?#]+)(?::(\d+))?/i.exec(url);
  if (!m) return null;
  return { host: m[1].toLowerCase(), port: m[2] || '' };
}

export function stagingProblem(baseUrl) {
  const url = String(baseUrl || '').trim();
  if (!url) return 'BASE_URL is not set. Point it at the STAGING API, e.g. -e BASE_URL=https://pic-staging.example.com';
  const parsed = hostOf(url);
  if (!parsed) return `BASE_URL must start with http:// or https:// (got "${url}")`;
  if (url.toLowerCase().indexOf('neon.tech') !== -1) {
    return 'BASE_URL contains "neon.tech". That is a database host, and load tests never touch the production Neon database. Use the staging API URL.';
  }
  const production = String(__ENV.PIC_PRODUCTION_HOSTS || '')
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter((s) => s.length > 0);
  const hostPort = parsed.port ? `${parsed.host}:${parsed.port}` : parsed.host;
  for (const entry of production) {
    if (entry === parsed.host || entry === hostPort || parsed.host.endsWith(`.${entry}`)) {
      return `BASE_URL host "${parsed.host}" is listed in PIC_PRODUCTION_HOSTS (${entry}). Load tests run against staging only.`;
    }
  }
  if (__ENV.PIC_LOAD_CONFIRM_STAGING !== 'yes') {
    return 'Set PIC_LOAD_CONFIRM_STAGING=yes to confirm BASE_URL is a STAGING environment with its own database (never production Neon).';
  }
  return null;
}

// Init context: throwing aborts the whole run before VUs start.
export function assertStagingTarget(baseUrl) {
  const problem = stagingProblem(baseUrl);
  if (problem) throw new Error(`[pic-load guard] refusing to run: ${problem}`);
}

// setup(): abort the test (exit code 108) with the same reason.
export function abortUnlessStaging(baseUrl) {
  const problem = stagingProblem(baseUrl);
  if (problem) exec.test.abort(`[pic-load guard] refusing to run: ${problem}`);
}
