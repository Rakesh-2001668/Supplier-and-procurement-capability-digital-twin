import { NextRequest, NextResponse } from 'next/server';
import { SESSION_COOKIE } from '@/lib/pic/server';
import { callApi, finishSignInStep } from '../session';

// Header organisation switcher: a new session in another organisation the person proved at sign-in. When that organisation's user has
// an authenticator, the answer is the MFA second step (the page then shows the code form on the sign-in page).
export async function POST(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ code: 'UNAUTHENTICATED', title: 'UNAUTHENTICATED', detail: 'Sign in first.' }, { status: 401 });
  }
  const { organisation } = await request.json().catch(() => ({ organisation: '' }));
  return finishSignInStep(request, await callApi(request, '/v1/auth/switch', { body: { organisation: String(organisation ?? '') }, token }));
}
