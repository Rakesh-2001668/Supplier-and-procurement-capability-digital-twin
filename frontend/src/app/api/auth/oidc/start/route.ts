import { NextRequest, NextResponse } from 'next/server';
import { callApi, OIDC_NEXT_COOKIE, OIDC_STATE_COOKIE, setStepCookie } from '../../session';

// Starts single sign-on: asks the API for the identity provider's authorization URL (PKCE + signed state) and redirects there.
// The state is also kept in an httpOnly cookie so the callback only completes a sign-in this browser started.
export async function GET(request: NextRequest) {
  const tenant = (request.nextUrl.searchParams.get('tenant') ?? '').trim().toUpperCase();
  const next = request.nextUrl.searchParams.get('next') ?? '';
  const fail = (code: string) => NextResponse.redirect(new URL(`/pic/login?sso=${encodeURIComponent(code)}`, request.url));
  if (!/^[A-Z0-9_]{1,20}$/.test(tenant)) return fail('OIDC_NOT_CONFIGURED');
  const result = await callApi(request, `/v1/auth/oidc/${encodeURIComponent(tenant)}/start`, { method: 'GET' });
  if (!result.ok || typeof result.data?.authorizationUrl !== 'string') return fail(result.data?.code ?? 'OIDC_NOT_CONFIGURED');
  const response = NextResponse.redirect(result.data.authorizationUrl);
  setStepCookie(response, request, OIDC_STATE_COOKIE, result.data.state, Number(result.data.expiresIn ?? 600));
  if (next.startsWith('/pic') && !next.startsWith('/pic/login')) setStepCookie(response, request, OIDC_NEXT_COOKIE, next, 600);
  return response;
}
