// Sign-in throughput and latency: POST /v1/auth/token (bcrypt cost 10, CPU-bound) then GET /v1/me.
// Valid credentials only: failed sign-ins count towards the 10-per-IP/5-minute brute-force block.
// Users: SIGNIN_EMAILS (default buyer, requester, buyer.lead @axion.example), password PASSWORD.
//
//   k6 run -e BASE_URL=https://pic-staging.example.com -e PIC_LOAD_CONFIRM_STAGING=yes -e PASSWORD=... signin.js
import { setupFor, signinFlow } from './lib/flows.js';
import { expectedRequestsPerMinute, standaloneOptions } from './lib/options.js';

export const options = standaloneOptions('signin');

export function setup() {
  // No pooled tokens are needed; setup only runs the guard, the health probe and one sign-in check.
  return setupFor({ roles: ['buyer'], expectedRequestsPerMinute: expectedRequestsPerMinute(['signin']) });
}

export default function () {
  signinFlow();
}
