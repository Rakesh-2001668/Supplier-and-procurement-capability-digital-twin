// PO detail page: GET /v1/purchase-orders/{ref} (header, lines, validation, lineage, process history,
// ETag) and GET /v1/purchase-orders/{ref}/schedule. PO numbers come from PO_NUMBERS (e.g. PO-77410)
// or are discovered from GET /v1/purchase-orders in setup. NFR: transactional, P95 < 400 ms.
//
//   k6 run -e BASE_URL=https://pic-staging.example.com -e PIC_LOAD_CONFIRM_STAGING=yes -e PASSWORD=... po_detail.js
import { poDetailFlow, setupFor } from './lib/flows.js';
import { expectedRequestsPerMinute, standaloneOptions } from './lib/options.js';

export const options = standaloneOptions('po_detail');

export function setup() {
  return setupFor({ roles: ['buyer'], poNumbers: true, expectedRequestsPerMinute: expectedRequestsPerMinute(['po_detail']) });
}

export default function (data) {
  poDetailFlow(data);
}
