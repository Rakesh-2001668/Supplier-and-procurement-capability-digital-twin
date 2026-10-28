// Requisition create + submit (WRITES DATA; staging only).
//   POST /v1/requisitions            MANUAL requisition, one MATERIAL/STOCK line of a seeded material
//                                    (default FK-M8-50, plant P100, standard price), Idempotency-Key per iteration
//   POST /v1/requisitions (replay)   IDEMPOTENCY_REPLAY_RATIO of iterations resend the same key and body and
//                                    expect the original response with replayed=true (no second document)
//   POST /v1/requisitions/{ref}/submit  policy + budget + DMN-01 routing; opens one approval task
// Every iteration leaves an IN_APPROVAL requisition and an open COST_OBJECT_OWNER task on staging.
// NFR: transactional, P95 < 400 ms.
//
//   k6 run -e BASE_URL=https://pic-staging.example.com -e PIC_LOAD_CONFIRM_STAGING=yes -e PASSWORD=... requisition_create_submit.js
import { requisitionFlow, setupFor } from './lib/flows.js';
import { expectedRequestsPerMinute, standaloneOptions } from './lib/options.js';

export const options = standaloneOptions('requisition_create_submit');

export function setup() {
  return setupFor({
    roles: ['requester'],
    requisitionLine: true,
    expectedRequestsPerMinute: expectedRequestsPerMinute(['requisition_create_submit']),
  });
}

export default function (data) {
  requisitionFlow(data);
}
