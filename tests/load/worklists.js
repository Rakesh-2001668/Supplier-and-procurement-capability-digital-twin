// Worklists: a buyer's home screen. GET /v1/tasks (approval inbox), GET /v1/notifications/unread-count,
// then the cursor-paginated lists /v1/requisitions, /v1/purchase-orders (open and all), /v1/invoices
// (exceptions) and /v1/goods-receipts, following nextCursor for up to WORKLIST_MAX_PAGES pages.
// NFR: transactional, P95 < 400 ms.
//
//   k6 run -e BASE_URL=https://pic-staging.example.com -e PIC_LOAD_CONFIRM_STAGING=yes -e PASSWORD=... worklists.js
import { setupFor, worklistsFlow } from './lib/flows.js';
import { expectedRequestsPerMinute, standaloneOptions } from './lib/options.js';

export const options = standaloneOptions('worklists');

export function setup() {
  return setupFor({ roles: ['buyer'], expectedRequestsPerMinute: expectedRequestsPerMinute(['worklists']) });
}

export default function (data) {
  worklistsFlow(data);
}
