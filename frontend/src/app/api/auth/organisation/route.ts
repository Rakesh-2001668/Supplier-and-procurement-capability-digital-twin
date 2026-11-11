import { NextRequest, NextResponse } from 'next/server';
import { callApi, CHOICE_COOKIE, finishSignInStep } from '../session';

// Sign-in by e-mail, second step when the e-mail belongs to several organisations: continue in the chosen organisation with the choice
// challenge kept in the httpOnly cookie by /api/auth/login. The answer is the session, the MFA second step or MFA enrolment.
export async function POST(request: NextRequest) {
  const challenge = request.cookies.get(CHOICE_COOKIE)?.value;
  if (!challenge) {
    return NextResponse.json({ code: 'ORGANISATION_CHOICE_INVALID', title: 'ORGANISATION_CHOICE_INVALID',
      detail: 'The sign-in step has expired; sign in again.' }, { status: 401 });
  }
  const { organisation } = await request.json().catch(() => ({ organisation: '' }));
  const result = await callApi(request, '/v1/auth/organisation', { body: { challenge, organisation: String(organisation ?? '') } });
  const response = await finishSignInStep(request, result);
  if (!result.ok && result.data?.code === 'ORGANISATION_CHOICE_INVALID') response.cookies.delete(CHOICE_COOKIE);
  return response;
}
