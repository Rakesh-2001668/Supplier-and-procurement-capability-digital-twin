import { NextRequest, NextResponse } from 'next/server';
import { callApi, ENROL_COOKIE, establishSession, MFA_COOKIE, setStepCookie } from '../session';

// Signs in against the PIC API and stores the access token in an httpOnly cookie.
// With a confirmed authenticator the API answers with an MFA challenge instead; it is kept in an httpOnly cookie for
// POST /api/auth/mfa. When the role requires MFA and none is registered, the enrolment challenge is kept for /api/auth/mfa/enrol.
export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const token = await callApi(request, '/v1/auth/token', { body });
  if (!token.ok) {
    const { enrolmentChallenge, ...problem } = token.data ?? {};
    const response = NextResponse.json(problem, { status: token.status });
    if (token.data?.code === 'MFA_ENROLMENT_REQUIRED' && typeof enrolmentChallenge === 'string') {
      setStepCookie(response, request, ENROL_COOKIE, enrolmentChallenge, 15 * 60);
    }
    return response;
  }
  if (token.data.mfaRequired) {
    const response = NextResponse.json({ mfaRequired: true, methods: token.data.methods ?? ['TOTP'] });
    setStepCookie(response, request, MFA_COOKIE, token.data.challenge, Number(token.data.expiresIn ?? 300));
    return response;
  }
  const { response } = await establishSession(request, token.data.access_token);
  return response;
}
