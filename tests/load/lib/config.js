// Run configuration from environment variables (k6 -e NAME=value or the process environment).
//
// Importing this module runs the staging guard (lib/guard.js) in the init context, so every
// script refuses to start against production before a single request is sent.
import { assertStagingTarget } from './guard.js';

function env(name, fallback) {
  const value = __ENV[name];
  return value === undefined || value === '' ? fallback : value;
}

function list(name, fallback) {
  return String(env(name, fallback))
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function num(name, fallback) {
  const raw = env(name, undefined);
  if (raw === undefined) return fallback;
  const value = Number(raw);
  if (!isFinite(value)) throw new Error(`${name} must be a number, got "${raw}"`);
  return value;
}

const baseUrl = String(env('BASE_URL', '')).replace(/\/+$/, '');
assertStagingTarget(baseUrl);

export const config = {
  baseUrl,
  tenant: env('TENANT', 'AXN'),
  // Shared password of the seeded demo users (PIC_SEED_PASSWORD on the staging seed). Never logged.
  password: env('PASSWORD', ''),

  // User pools. A comma-separated list spreads VUs over several users, which keeps each user
  // under the per-user rate limit. Defaults are the seeded AXN users (backend/app/pic/seed/axion.py).
  users: {
    buyer: list('BUYER_EMAILS', env('BUYER_EMAIL', 'buyer@axion.example')), // BUYER: worklists, PO detail
    requester: list('REQUESTER_EMAILS', env('REQUESTER_EMAIL', 'requester@axion.example')), // REQUESTER: req:create
    ap: list('AP_EMAILS', env('AP_EMAIL', 'ap.clerk@axion.example')), // AP_CLERK: invoice:capture + invoice:resolve
    spend: list('SPEND_EMAILS', env('SPEND_EMAIL', 'category.manager@axion.example')), // CATEGORY_MANAGER: spend:read
    signin: list('SIGNIN_EMAILS', 'buyer@axion.example,requester@axion.example,buyer.lead@axion.example'),
  },

  // Load shape (standalone scripts). Rates are iterations per minute.
  smoke: env('SMOKE', '') === '1',
  ratePerMin: num('RATE_PER_MIN', 0), // 0 = the script's own default
  duration: env('DURATION', '5m'),
  rampUp: env('RAMP_UP', '2m'),
  rampDown: env('RAMP_DOWN', '1m'),
  loadFactor: num('LOAD_FACTOR', 1), // all.js: multiplies every scenario's arrival rate
  preAllocatedVUs: num('VUS', 0),
  maxVUs: num('MAX_VUS', 0),
  thinkTimeMax: num('THINK_TIME_MAX', 1.0), // seconds of random pause between user steps
  requestTimeout: env('REQUEST_TIMEOUT', '30s'),
  maxErrorLogsPerVu: num('MAX_ERROR_LOGS_PER_VU', 20),

  // Worklists
  worklistPageSize: num('WORKLIST_PAGE_SIZE', 50),
  worklistMaxPages: num('WORKLIST_MAX_PAGES', 2),

  // PO detail: explicit numbers (e.g. PO-77410,PO-77411) or discovered from GET /v1/purchase-orders in setup.
  poNumbers: list('PO_NUMBERS', ''),

  // Requisition line, taken from the seeded material master (FK-M8-50 fastener kit, STOCK, plant P100).
  reqMaterial: env('REQ_MATERIAL', 'FK-M8-50'),
  reqPlant: env('REQ_PLANT', 'P100'),
  reqStorageLocation: env('REQ_STORAGE_LOCATION', '0001'),
  reqPurposeCode: env('REQ_PURPOSE_CODE', 'LINE_SUPPLIES'),
  replayRatio: num('IDEMPOTENCY_REPLAY_RATIO', 0.05),

  // Invoice match: PO and line to invoice against (discovered in setup when not given).
  invoicePo: env('INVOICE_PO', ''),
  invoicePoLine: num('INVOICE_PO_LINE', 0),
  invoiceDateBase: env('INVOICE_DATE_BASE', ''), // YYYY-MM-DD; default today (UTC)
  priceVarianceRatio: num('PRICE_VARIANCE_RATIO', 0.25),

  // Spend cube slices: semicolon-separated, each a comma-separated dims list for GET /v1/spend/cube?dims=...
  // Allowed dims (services/savings.py): category, supplier, plant, company_code, period, material_group, cost_object.
  spendCubeDims: String(env('SPEND_CUBE_DIMS', 'category;supplier,period;plant,material_group'))
    .split(';')
    .map((s) => s.trim())
    .filter((s) => s.length > 0),
};

// Expected rate-limit settings on the target (for the pre-flight warning only; the API enforces them).
export const rateLimits = {
  perIp: num('PIC_RATE_LIMIT_PER_IP', 600),
  perUser: num('PIC_RATE_LIMIT_PER_USER', 1200),
  windowSeconds: num('PIC_RATE_LIMIT_WINDOW_SECONDS', 60),
};
