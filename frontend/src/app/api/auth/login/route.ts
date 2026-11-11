import { NextRequest } from 'next/server';
import { callApi, finishSignInStep } from '../session';

// Signs in against the PIC API by e-mail and password (the organisation is found from the e-mail; an API client may still send an
// organisation code). The answer is the session, the organisation choice (e-mail in several organisations), the MFA second step or
// MFA enrolment; the challenges for the next step are kept in httpOnly cookies.
export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const payload = {
    email: String(body?.email ?? ''),
    password: String(body?.password ?? ''),
    ...(body?.tenant ? { tenant: String(body.tenant) } : {}),
  };
  return finishSignInStep(request, await callApi(request, '/v1/auth/token', { body: payload }));
}
