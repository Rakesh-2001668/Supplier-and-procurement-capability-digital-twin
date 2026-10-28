import { NextRequest, NextResponse } from 'next/server';
import { apiBase, clientIp, SESSION_COOKIE, SESSION_MAX_AGE, USER_COOKIE } from '@/lib/pic/server';

// Signs in against the PIC API and stores the access token in an httpOnly cookie.
export async function POST(request: NextRequest) {
  const body = await request.text();
  const forwarded = clientIp(request.headers);
  const tokenResponse = await fetch(`${apiBase()}/v1/auth/token`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...(forwarded ? { 'x-forwarded-for': forwarded } : {}) },
    body,
    cache: 'no-store',
  });
  const token = await tokenResponse.json();
  if (!tokenResponse.ok) {
    return NextResponse.json(token, { status: tokenResponse.status });
  }
  const meResponse = await fetch(`${apiBase()}/v1/me`, {
    headers: { authorization: `Bearer ${token.access_token}` },
    cache: 'no-store',
  });
  const me = await meResponse.json();
  const user = {
    id: me.userId,
    name: me.name,
    email: me.user,
    tenant: me.tenant,
    roles: me.roles,
    supplierId: me.supplierId,
  };
  const response = NextResponse.json({ user });
  // Secure cookies whenever the browser reached us over HTTPS (directly or via a TLS-terminating proxy).
  const secure = request.nextUrl.protocol === 'https:' || request.headers.get('x-forwarded-proto') === 'https';
  response.cookies.set(SESSION_COOKIE, token.access_token, {
    httpOnly: true,
    sameSite: 'lax',
    secure,
    path: '/',
    maxAge: SESSION_MAX_AGE,
  });
  // Display-only profile (no secrets) so the shell can render names and roles without a round trip.
  response.cookies.set(USER_COOKIE, encodeURIComponent(JSON.stringify(user)), {
    httpOnly: false,
    sameSite: 'lax',
    secure,
    path: '/',
    maxAge: SESSION_MAX_AGE,
  });
  return response;
}
