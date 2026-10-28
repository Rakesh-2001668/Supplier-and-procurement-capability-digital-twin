// Spend analytics: GET /v1/spend/overview, GET /v1/spend/cube?dims=... (SPEND_CUBE_DIMS slices),
// GET /v1/spend/treemap, GET /v1/spend/suppliers and the command-centre GET /v1/dashboard.
// User needs spend:read (default category.manager@axion.example). NFR: spend, P95 < 3 s.
//
//   k6 run -e BASE_URL=https://pic-staging.example.com -e PIC_LOAD_CONFIRM_STAGING=yes -e PASSWORD=... spend_overview.js
import { setupFor, spendFlow } from './lib/flows.js';
import { expectedRequestsPerMinute, standaloneOptions } from './lib/options.js';

export const options = standaloneOptions('spend_overview');

export function setup() {
  return setupFor({ roles: ['spend'], expectedRequestsPerMinute: expectedRequestsPerMinute(['spend_overview']) });
}

export default function (data) {
  spendFlow(data);
}
