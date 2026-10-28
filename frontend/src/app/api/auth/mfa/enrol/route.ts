import { NextRequest, NextResponse } from 'next/server';
import { callApi, ENROL_COOKIE, establishSession } from '../../session';

// Enrolment during sign-in (MFA_ENROLMENT_REQUIRED): the enrolment challenge from /api/auth/login opens only the
// authenticator endpoints. action "start" returns the key and otpauth URI; "confirm" checks the code and completes sign-in.
export async function POST(request: NextRequest) {
  const challenge = request.cookies.get(ENROL_COOKIE)?.value;
  if (!challenge) {
    return NextResponse.json({ code: 'CHALLENGE_INVALID', title: 'CHALLENGE_INVALID', detail: 'The enrolment step has expired; sign in again.' },
      { status: 401 });
  }
  const body = await request.json().catch(() => ({}));
  if (body.action === 'confirm') {
    const result = await callApi(request, '/v1/me/mfa/totp/confirm', { token: challenge, body: { code: String(body.code ?? '').replace(/\s/g, '') } });
    if (!result.ok) return NextResponse.json(result.data, { status: result.status });
    const { response } = await establishSession(request, result.data.access_token);
    return response;
  }
  const result = await callApi(request, '/v1/me/mfa/totp', { token: challenge });
  return NextResponse.json(result.data, { status: result.status });
}
