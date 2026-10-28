// Invoice capture + match (WRITES DATA; staging only).
//   POST /v1/invoices                 captures a new PORTAL invoice against a seeded PO line with a goods
//                                     receipt; capture runs the duplicate check and the 3/4-way match inline
//   POST /v1/invoices/{ref}/match     re-match of the test's own invoice when it landed in EXCEPTION
//                                     (PRICE_VARIANCE_RATIO of invoices bill 3 % over the PO price on purpose)
// Why a new invoice per iteration instead of re-matching a seeded one: see invoiceMatchFlow in lib/flows.js.
// Invoices are never approved or posted, so the PO line's open quantity is never consumed.
// NFR: transactional, P95 < 400 ms.
//
//   k6 run -e BASE_URL=https://pic-staging.example.com -e PIC_LOAD_CONFIRM_STAGING=yes -e PASSWORD=... invoice_match.js
import { invoiceMatchFlow, setupFor } from './lib/flows.js';
import { expectedRequestsPerMinute, standaloneOptions } from './lib/options.js';

export const options = standaloneOptions('invoice_match');

export function setup() {
  return setupFor({ roles: ['ap'], invoiceTarget: true, expectedRequestsPerMinute: expectedRequestsPerMinute(['invoice_match']) });
}

export default function (data) {
  invoiceMatchFlow(data);
}
