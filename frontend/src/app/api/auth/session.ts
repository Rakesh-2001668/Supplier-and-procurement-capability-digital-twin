import { NextRequest, NextResponse } from 'next/server';
import { apiBase, clientIp, SESSION_COOKIE, SESSION_MAX_AGE, USER_COOKIE } from '@/lib/pic/server';

// Shared by the sign-in routes (password, MFA step, MFA enrolment, OIDC callback).
// Short-lived sign-in steps (MFA challenge, enrolment challenge, OIDC state) also live in httpOnly cookies, never in page script.

export const MFA_COOKIE = 'pic_mfa';
export const ENROL_COOKIE = 'pic_mfa_enrol';
export const OIDC_STATE_COOKIE = 'pic_oidc_state';
export const OIDC_NEXT_COOKIE = 'pic_oidc_next';

export function isSecure(request: NextRequest): boolean {
  return request.nextUrl.protocol === 'https:' || request.headers.get('x-forwarded-proto') === 'https';
}

export function upstreamHeaders(request: NextRequest, extra: Record<string, string> = {}): Record<string, string> {
  const forwarded = clientIp(request.headers);
  return { 'content-type': 'application/json', ...(forwarded ? { 'x-forwarded-for': forwarded } : {}), ...extra };
}

export async function callApi(request: NextRequest, path: string, init: { method?: string; body?: unknown; token?: string } = {}) {
  try {
    const response = await fetch(`${apiBase()}${path}`, {
      method: init.method ?? 'POST',
      headers: upstreamHeaders(request, init.token ? { authorization: `Bearer ${init.token}` } : {}),
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      cache: 'no-store',
    });
    const text = await response.text();
    return { ok: response.ok, status: response.status, data: text ? JSON.parse(text) : {} };
  } catch {
    return {
      ok: false, status: 502,
      data: { code: 'API_UNAVAILABLE', title: 'API_UNAVAILABLE', detail: 'The procurement API is not reachable. Check that it is running.' },
    };
  }
}

export function setStepCookie(response: NextResponse, request: NextRequest, name: string, value: string, maxAge: number) {
  response.cookies.set(name, value, { httpOnly: true, sameSite: 'lax', secure: isSecure(request), path: '/', maxAge });
}

/** Store the access token (httpOnly) and the display profile, and clear any pending sign-in step. */
export async function establishSession(request: NextRequest, accessToken: string, response?: NextResponse) {
  const meResponse = await fetch(`${apiBase()}/v1/me`, { headers: { authorization: `Bearer ${accessToken}` }, cache: 'no-store' });
  const me = await meResponse.json();
  const user = { id: me.userId, name: me.name, email: me.user, tenant: me.tenant, roles: me.roles, supplierId: me.supplierId };
  const out = response ?? NextResponse.json({ user });
  const secure = isSecure(request);
  out.cookies.set(SESSION_COOKIE, accessToken, { httpOnly: true, sameSite: 'lax', secure, path: '/', maxAge: SESSION_MAX_AGE });
  // Display-only profile (no secrets) so the shell can render names and roles without a round trip.
  out.cookies.set(USER_COOKIE, encodeURIComponent(JSON.stringify(user)), { httpOnly: false, sameSite: 'lax', secure, path: '/', maxAge: SESSION_MAX_AGE });
  for (const name of [MFA_COOKIE, ENROL_COOKIE, OIDC_STATE_COOKIE, OIDC_NEXT_COOKIE]) out.cookies.delete(name);
  return { response: out, user };
}
