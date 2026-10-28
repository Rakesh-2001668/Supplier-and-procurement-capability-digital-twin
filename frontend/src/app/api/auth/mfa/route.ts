import { NextRequest, NextResponse } from 'next/server';
import { callApi, establishSession, MFA_COOKIE } from '../session';

// Second sign-in step: the authenticator code plus the challenge kept in the httpOnly cookie by /api/auth/login.
export async function POST(request: NextRequest) {
  const challenge = request.cookies.get(MFA_COOKIE)?.value;
  if (!challenge) {
    return NextResponse.json({ code: 'MFA_CHALLENGE_INVALID', title: 'MFA_CHALLENGE_INVALID', detail: 'The sign-in step has expired; sign in again.' },
      { status: 401 });
  }
  const { code } = await request.json().catch(() => ({ code: '' }));
  const result = await callApi(request, '/v1/auth/mfa', { body: { challenge, code: String(code ?? '').replace(/\s/g, '') } });
  if (!result.ok) {
    const response = NextResponse.json(result.data, { status: result.status });
    if (['MFA_CHALLENGE_INVALID', 'MFA_CHALLENGE_EXHAUSTED'].includes(result.data?.code)) response.cookies.delete(MFA_COOKIE);
    return response;
  }
  const { response } = await establishSession(request, result.data.access_token);
  return response;
}
