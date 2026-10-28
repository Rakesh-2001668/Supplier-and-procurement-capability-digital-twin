import { NextRequest, NextResponse } from 'next/server';
import { callApi, establishSession, OIDC_NEXT_COOKIE, OIDC_STATE_COOKIE } from '../../session';

// Redirect URI registered at the identity provider (PIC_OIDC_<TENANT>_REDIRECT_URI = https://<web>/api/auth/oidc/callback).
// Completes the authorization-code flow through the API and sets the session cookie like the password sign-in.
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const fail = (code: string) => {
    const response = NextResponse.redirect(new URL(`/pic/login?sso=${encodeURIComponent(code)}`, request.url));
    response.cookies.delete(OIDC_STATE_COOKIE);
    response.cookies.delete(OIDC_NEXT_COOKIE);
    return response;
  };
  if (params.get('error')) return fail(`IDP_${params.get('error')!.toUpperCase()}`);
  const code = params.get('code');
  const state = params.get('state');
  const expected = request.cookies.get(OIDC_STATE_COOKIE)?.value;
  if (!code || !state || !expected || state !== expected) return fail('OIDC_STATE_INVALID');
  const result = await callApi(request, '/v1/auth/oidc/callback', { body: { code, state } });
  if (!result.ok) return fail(result.data?.code ?? 'OIDC_FAILED');
  const next = request.cookies.get(OIDC_NEXT_COOKIE)?.value;
  const roles: string[] = result.data.roles ?? [];
  const target = next && next.startsWith('/pic') ? next : roles.includes('SUPPLIER_USER') ? '/pic/portal' : '/pic';
  const { response } = await establishSession(request, result.data.access_token, NextResponse.redirect(new URL(target, request.url)));
  return response;
}
