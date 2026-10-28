// User journeys shared by the standalone scripts and all.js.
//
// Endpoints and bodies are taken from the API modules (backend/app/pic/api/*.py) and the seed
// (backend/app/pic/seed/axion.py, operations.py). Document numbers are discovered in setup() from the
// staging data instead of being hard-coded, because number ranges depend on the seed run.
import { group, sleep } from 'k6';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';
import { config, rateLimits } from './config.js';
import { abortUnlessStaging } from './guard.js';
import { call, sessionFor, signIn, signInPools } from './auth.js';
import { checkBody, idempotencyKey, json, KIND, request } from './http.js';

const T = KIND.transactional;
const S = KIND.spend;

export const invoiceOutcome = new Counter('pic_invoice_outcome');
export const requisitionsSubmitted = new Counter('pic_requisitions_submitted');

function think() {
  if (config.thinkTimeMax > 0) sleep(Math.random() * config.thinkTimeMax);
}

function enc(ref) {
  return encodeURIComponent(ref);
}

function isoDate(d) {
  return d.toISOString().slice(0, 10);
}

function addDays(base, days) {
  const d = new Date(`${base}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return isoDate(d);
}

function num(v) {
  const n = parseFloat(v);
  return isFinite(n) ? n : 0;
}

// ------------------------------------------------------------------------------------------- setup
// needs: { roles: [...], poNumbers, invoiceTarget, requisitionLine }
export function setupFor(needs) {
  abortUnlessStaging(config.baseUrl);

  const health = request('GET', '/healthz', { name: 'GET /healthz', kind: KIND.setup });
  if (health.status !== 200) {
    exec.test.abort(`[setup] ${config.baseUrl}/healthz returned ${health.status}; is the staging API up?`);
  }
  warnAboutRateLimits(needs.expectedRequestsPerMinute || 0);

  const data = { sessions: signInPools(needs.roles), runId: Date.now().toString(36).slice(-6) };
  const any = data.sessions[needs.roles[0]][0];

  if (needs.poNumbers) data.poNumbers = discoverPoNumbers(any);
  if (needs.requisitionLine) data.requisitionLine = resolveRequisitionLine(data.sessions.requester[0]);
  if (needs.invoiceTarget) data.invoiceTarget = discoverInvoiceTarget(data.sessions.ap[0]);
  return data;
}

function warnAboutRateLimits(perMinute) {
  if (!perMinute) return;
  const perWindow = (perMinute * rateLimits.windowSeconds) / 60;
  if (perWindow > rateLimits.perIp * 0.8) {
    console.warn(
      `[setup] this run sends about ${Math.round(perWindow)} requests per ${rateLimits.windowSeconds}s window from one IP; ` +
        `the API default is ${rateLimits.perIp} per IP per replica. Raise PIC_RATE_LIMIT_PER_IP / PIC_RATE_LIMIT_PER_USER on the ` +
        'STAGING API (README, "Rate limits") or expect 429s. Set PIC_RATE_LIMIT_PER_IP here to the staging value to silence this.',
    );
  }
}

function discoverPoNumbers(session) {
  if (config.poNumbers.length) return config.poNumbers;
  const numbers = [];
  let cursor = null;
  for (let page = 0; page < 5; page++) {
    const q = `/v1/purchase-orders?limit=200${cursor ? `&cursor=${enc(cursor)}` : ''}`;
    const res = call(session, 'GET', q, { name: 'GET /v1/purchase-orders', kind: KIND.setup });
    const body = json(res);
    if (res.status !== 200 || !body) break;
    body.items.forEach((po) => numbers.push(po.number));
    cursor = body.nextCursor;
    if (!cursor) break;
  }
  if (!numbers.length) exec.test.abort('[setup] no purchase orders found; seed staging with python -m app.pic.seed or set PO_NUMBERS');
  return numbers;
}

// The requisition line is a seeded material (default FK-M8-50 fastener kit, STOCK, plant P100):
// the same kind of line as seed case 5 (operations.py). STOCK purchases need no account assignment,
// so submit does not commit cost-centre budget and the test can run indefinitely without hitting
// BUDGET_EXCEEDED. The estimated price is the material's standard price from GET /v1/reference.
function resolveRequisitionLine(session) {
  const res = call(session, 'GET', '/v1/reference', { name: 'GET /v1/reference', kind: KIND.setup });
  const body = json(res);
  if (res.status !== 200 || !body) exec.test.abort('[setup] GET /v1/reference failed');
  const material = (body.materials || []).filter((m) => m.number === config.reqMaterial)[0];
  if (!material) exec.test.abort(`[setup] material ${config.reqMaterial} not in /v1/reference; set REQ_MATERIAL to a seeded material`);
  const plant = (body.plants || []).filter((p) => p.code === config.reqPlant)[0];
  if (!plant) exec.test.abort(`[setup] plant ${config.reqPlant} not in /v1/reference; set REQ_PLANT`);
  if (!material.standardPriceMinor) exec.test.abort(`[setup] material ${config.reqMaterial} has no standard price`);
  return { material: material.number, uom: material.uom, priceMinor: material.standardPriceMinor, plant: plant.code };
}

// Invoice target: a PO line with goods received but not (fully) invoiced, e.g. the seeded FK-M8-50
// fastener PO (operations.py case 5: 2,000 received, nothing invoiced, 3-way match).
// invoiced_qty only moves when an invoice is POSTED (payables._invoice_posted); captured and matched
// invoices do not consume the open quantity, so every iteration can match against the same line.
function discoverInvoiceTarget(session) {
  const candidates = [];
  if (config.invoicePo) {
    candidates.push(config.invoicePo);
  } else {
    const res = call(session, 'GET', '/v1/goods-receipts?limit=200', { name: 'GET /v1/goods-receipts', kind: KIND.setup });
    const body = json(res);
    if (res.status === 200 && body) {
      body.items.forEach((gr) => {
        if (gr.po && candidates.indexOf(gr.po) === -1) candidates.push(gr.po);
      });
    }
  }
  let best = null;
  candidates.slice(0, 30).forEach((poNumber) => {
    const res = call(session, 'GET', `/v1/purchase-orders/${enc(poNumber)}`, { name: 'GET /v1/purchase-orders/{ref}', kind: KIND.setup });
    const po = json(res);
    if (res.status !== 200 || !po || !po.lines) return;
    po.lines.forEach((l) => {
      if (config.invoicePoLine && l.line_no !== config.invoicePoLine) return;
      if (!l.gr_required || l.ses_required || l.ers) return;
      const basis = l.quality_managed ? num(l.accepted_qty) : num(l.received_qty) - num(l.rejected_qty);
      const open = Math.floor(basis - num(l.invoiced_qty));
      if (open < 1) return;
      if (!best || open > best.openQty) {
        best = {
          po: po.number,
          line: l.line_no,
          supplier: po.supplier.code,
          unitPriceMinor: l.unit_price_minor,
          openQty: open,
          match: l.quality_managed ? '4WAY' : '3WAY',
        };
      }
    });
  });
  if (!best) {
    exec.test.abort(
      '[setup] no PO line with received-but-uninvoiced quantity found. Seed staging (python -m app.pic.seed) or set INVOICE_PO / INVOICE_PO_LINE.',
    );
  }
  best.maxQty = Math.max(1, Math.min(best.openQty, 2000));
  // Different runs start at different (qty, date) points to avoid fuzzy-duplicate holds against earlier runs.
  best.salt = Math.floor(Math.random() * best.maxQty * 30);
  best.dateBase = config.invoiceDateBase || isoDate(new Date());
  console.log(`[setup] invoice target ${best.po} line ${best.line} (${best.supplier}, ${best.match}, open ${best.openQty})`);
  return best;
}

// ------------------------------------------------------------------------------------------- flows

// Sign-in: valid credentials only (failed sign-ins count towards the 10-per-IP/5-min block).
export function signinFlow() {
  const pool = config.users.signin;
  const email = pool[exec.scenario.iterationInTest % pool.length];
  const result = signIn(email, KIND.auth);
  if (result.error) return;
  const me = request('GET', '/v1/me', { token: result.token, name: 'GET /v1/me' });
  checkBody(me, 'GET /v1/me', { 'tenant matches': (b) => b.tenant === config.tenant });
}

// Worklists: what a buyer's home screen loads (task inbox, notifications badge and the main lists),
// following nextCursor for up to WORKLIST_MAX_PAGES pages (api/pagination.py, max 200 per page).
const WORKLISTS = [
  { name: 'GET /v1/requisitions', path: '/v1/requisitions?status=APPROVED' },
  { name: 'GET /v1/purchase-orders', path: '/v1/purchase-orders?status=RELEASED,TRANSMITTED,CONFIRMED,PARTIALLY_RECEIVED' },
  { name: 'GET /v1/purchase-orders', path: '/v1/purchase-orders' },
  { name: 'GET /v1/invoices', path: '/v1/invoices?status=EXCEPTION' },
  { name: 'GET /v1/goods-receipts', path: '/v1/goods-receipts' },
];

function pagedList(session, list) {
  let cursor = null;
  for (let page = 1; page <= config.worklistMaxPages; page++) {
    const sep = list.path.indexOf('?') === -1 ? '?' : '&';
    const path = `${list.path}${sep}limit=${config.worklistPageSize}${cursor ? `&cursor=${enc(cursor)}` : ''}`;
    const res = call(session, 'GET', path, { name: list.name, kind: T, tags: { page: String(page) } });
    const body = checkBody(res, list.name, { 'items[] + nextCursor': (b) => Array.isArray(b.items) && 'nextCursor' in b });
    cursor = body && body.nextCursor;
    if (!cursor) return;
    think();
  }
}

export function worklistsFlow(data) {
  const s = sessionFor(data, 'buyer');
  group('worklists', () => {
    const tasks = call(s, 'GET', '/v1/tasks', { name: 'GET /v1/tasks', kind: T });
    checkBody(tasks, 'GET /v1/tasks', { 'array': (b) => Array.isArray(b) });
    call(s, 'GET', '/v1/notifications/unread-count', { name: 'GET /v1/notifications/unread-count', kind: T });
    think();
    WORKLISTS.forEach((list) => {
      pagedList(s, list);
      think();
    });
  });
}

// PO detail: header + lines + validation + lineage + process (views.purchase_order) and the schedule tab.
export function poDetailFlow(data) {
  const s = sessionFor(data, 'buyer');
  const n = data.poNumbers[Math.floor(Math.random() * data.poNumbers.length)];
  group('po_detail', () => {
    const res = call(s, 'GET', `/v1/purchase-orders/${enc(n)}`, { name: 'GET /v1/purchase-orders/{ref}', kind: T });
    checkBody(res, 'GET /v1/purchase-orders/{ref}', {
      'number matches': (b) => b.number === n,
      'has lines': (b) => Array.isArray(b.lines) && b.lines.length > 0,
      'has ETag': () => Boolean(res.headers.Etag || res.headers.ETag),
    });
    think();
    const sched = call(s, 'GET', `/v1/purchase-orders/${enc(n)}/schedule`, { name: 'GET /v1/purchase-orders/{ref}/schedule', kind: T });
    checkBody(sched, 'GET /v1/purchase-orders/{ref}/schedule', { 'array': (b) => Array.isArray(b) });
  });
}

// Requisition: POST /v1/requisitions (DRAFT, Idempotency-Key honoured) then POST /v1/requisitions/{ref}/submit.
// Submit runs policy (P01 purpose code), category budget, DMN-01 routing and starts the approval
// (one COST_OBJECT_OWNER task for this value band), so it is the heavier of the two calls.
// Only the requester may submit their own requisition, hence the REQUESTER pool for both calls.
export function requisitionFlow(data) {
  const s = sessionFor(data, 'requester');
  const line = data.requisitionLine;
  const qty = 50 * (2 + Math.floor(Math.random() * 9)); // 100..500 EA; value stays inside the lowest approval band
  const body = {
    origin: 'MANUAL',
    purpose_code: config.reqPurposeCode,
    purpose_text: `k6 load test ${data.runId}: fastener kits for ${line.plant} assembly`,
    plant: line.plant,
    company_code: '1000',
    lines: [
      {
        item_type: 'MATERIAL',
        purchase_type: 'STOCK',
        material: line.material,
        qty: String(qty),
        uom: line.uom,
        price_est_minor: line.priceMinor,
        need_date: addDays(isoDate(new Date()), 21),
        storage_location: config.reqStorageLocation,
      },
    ],
  };
  group('requisition_create_submit', () => {
    const key = idempotencyKey('req');
    const created = call(s, 'POST', '/v1/requisitions', { body, idempotencyKey: key, name: 'POST /v1/requisitions', kind: T, expected: [201] });
    const pr = checkBody(created, 'POST /v1/requisitions', {
      'DRAFT with number': (b) => b.status === 'DRAFT' && Boolean(b.number),
      'one line': (b) => b.lines.length === 1,
    });
    if (!pr || !pr.number) return;

    if (Math.random() < config.replayRatio) {
      // Same key + same body must replay the original response, not create a second requisition (§10.1).
      const replay = call(s, 'POST', '/v1/requisitions', {
        body, idempotencyKey: key, name: 'POST /v1/requisitions (replay)', kind: T, expected: [201],
      });
      checkBody(replay, 'POST /v1/requisitions (replay)', { 'replayed same number': (b) => b.replayed === true && b.number === pr.number });
    }
    think();
    const submitted = call(s, 'POST', `/v1/requisitions/${enc(pr.number)}/submit`, {
      body: { justification: 'k6 staging load test', request_sourcing: false },
      idempotencyKey: idempotencyKey('submit'), // not used by this endpoint today; harmless
      name: 'POST /v1/requisitions/{ref}/submit',
      kind: T,
    });
    const after = checkBody(submitted, 'POST /v1/requisitions/{ref}/submit', {
      'routed': (b) => ['IN_APPROVAL', 'APPROVED'].indexOf(b.status) !== -1,
    });
    if (after && after.status) requisitionsSubmitted.add(1, { status: after.status });
  });
}

// Invoice capture + match.
//
// Why not re-match a seeded invoice: POST /v1/invoices/{ref}/match only accepts EXCEPTION invoices
// (state machine EXCEPTION -> rematch); every call supersedes and re-creates exception rows, logs an
// agent run, emits an outbox event and notifies AP, and it takes a row lock on that one invoice, so
// N VUs would mostly measure lock waits on a single row and would rewrite the seeded demo history.
//
// Instead each iteration captures a NEW invoice (POST /v1/invoices) against a seeded PO line that has
// a goods receipt. Capture runs the duplicate check and the 2/3/4-way match synchronously
// (payables.capture -> _duplicate_check -> match), so its latency is the capture+match cost.
// PRICE_VARIANCE_RATIO of the invoices bill 3 % above the PO price (tolerance is 1 %, DMN-03), land in
// EXCEPTION with a PRICE exception, and are then re-matched with POST /v1/invoices/{ref}/match:
// that exercises the explicit match endpoint on an invoice the test owns. Invoices stay unposted, so the
// PO line's open quantity is never consumed.
//
// Fuzzy duplicate rule (DMN-03): same supplier, gross within 1 rupee and invoice date within 3 days.
// Quantity cycles 1..maxQty and the invoice date steps back 8 days per cycle (variance invoices sit
// 4 days off the matched ones), so invoices of one run never look like duplicates of each other.
export function invoiceMatchFlow(data) {
  const s = sessionFor(data, 'ap');
  const t = data.invoiceTarget;
  const n = exec.scenario.iterationInTest + t.salt;
  const qty = 1 + (n % t.maxQty);
  const variance = Math.random() < config.priceVarianceRatio;
  const bucket = Math.floor(n / t.maxQty) % 90;
  const invoiceDate = addDays(t.dateBase, -(bucket * 8) - (variance ? 4 : 0));
  const priceMinor = variance ? Math.round(t.unitPriceMinor * 1.03) : t.unitPriceMinor;
  const supplierInvoiceNo = `LT${data.runId}-${exec.vu.idInTest}-${exec.scenario.iterationInTest}`.slice(0, 22);
  const body = {
    supplier: t.supplier,
    supplier_invoice_no: supplierInvoiceNo,
    invoice_date: invoiceDate,
    channel: 'PORTAL',
    company_code: '1000',
    lines: [{ po: t.po, po_line: t.line, qty: String(qty), unit_price: (priceMinor / 100).toFixed(2) }],
  };
  group('invoice_match', () => {
    const res = call(s, 'POST', '/v1/invoices', {
      body, idempotencyKey: idempotencyKey('inv'), name: 'POST /v1/invoices', kind: T, expected: [201],
    });
    const inv = checkBody(res, 'POST /v1/invoices', {
      'matched or exception': (b) => b.status === 'MATCHED' || b.status === 'EXCEPTION',
      'match type set': (b) => Boolean(b.match_type),
    });
    if (!inv || !inv.status) return;
    const exceptions = (inv.exceptions || []).filter((e) => e.status === 'OPEN').map((e) => e.type);
    invoiceOutcome.add(1, { status: inv.status, variance: String(variance), exceptions: exceptions.join('+') || 'none' });
    if (inv.status !== 'EXCEPTION') return;
    think();
    const rematch = call(s, 'POST', `/v1/invoices/${enc(inv.number)}/match`, {
      idempotencyKey: idempotencyKey('match'), // not used by this endpoint today; harmless
      name: 'POST /v1/invoices/{ref}/match',
      kind: T,
    });
    checkBody(rematch, 'POST /v1/invoices/{ref}/match', {
      'result': (b) => b.invoice === inv.number && (b.status === 'MATCHED' || b.status === 'EXCEPTION'),
    });
  });
}

// Spend analytics (NFR: < 3 s): overview, cube slices, treemap, supplier view, command-centre dashboard.
// The dashboard aggregates spend lines too (services/insight.py), so it is held to the spend budget.
export function spendFlow(data) {
  const s = sessionFor(data, 'spend');
  group('spend_overview', () => {
    const ov = call(s, 'GET', '/v1/spend/overview', { name: 'GET /v1/spend/overview', kind: S });
    checkBody(ov, 'GET /v1/spend/overview', { 'totalMinor': (b) => typeof b.totalMinor === 'number' }, S);
    think();
    config.spendCubeDims.forEach((dims) => {
      const cube = call(s, 'GET', `/v1/spend/cube?dims=${enc(dims)}`, { name: 'GET /v1/spend/cube', kind: S, tags: { dims } });
      checkBody(cube, 'GET /v1/spend/cube', { 'rows[]': (b) => Array.isArray(b.rows) }, S);
      think();
    });
    call(s, 'GET', '/v1/spend/treemap', { name: 'GET /v1/spend/treemap', kind: S });
    think();
    call(s, 'GET', '/v1/spend/suppliers', { name: 'GET /v1/spend/suppliers', kind: S });
    think();
    call(s, 'GET', '/v1/dashboard', { name: 'GET /v1/dashboard', kind: S });
  });
}
