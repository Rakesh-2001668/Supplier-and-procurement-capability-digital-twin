import { NextRequest, NextResponse } from 'next/server';
import { apiBase, clientIp } from '@/lib/pic/server';

// M04 punch-out return: the supplier's catalogue posts the cart (cXML PunchOutOrderMessage or OCI NEW_ITEM-* fields) here
// through the user's browser. This is a cross-site form post, so no session cookie is expected: the API matches the cart to
// the session by its BuyerCookie. The browser is then sent back to the requisition page, which shows the cart.

const MAX_BODY = 2_000_000;

function back(request: NextRequest, params: Record<string, string>) {
  const url = new URL('/pic/requisitions/new', request.nextUrl.origin);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  return NextResponse.redirect(url, 303);
}

export async function POST(request: NextRequest) {
  const body = await request.text();
  if (body.length > MAX_BODY) return back(request, { punchoutError: 'PAYLOAD_TOO_LARGE' });
  const headers = new Headers({ 'content-type': request.headers.get('content-type') ?? 'application/x-www-form-urlencoded' });
  const ip = clientIp(request.headers);
  if (ip) headers.set('x-forwarded-for', ip);
  let upstream: Response;
  try {
    upstream = await fetch(`${apiBase()}/v1/punchout/return${request.nextUrl.search}`, { method: 'POST', headers, body, cache: 'no-store' });
  } catch {
    return back(request, { punchoutError: 'API_UNAVAILABLE' });
  }
  const data = await upstream.json().catch(() => null);
  if (!upstream.ok) {
    return back(request, { punchoutError: String(data?.code ?? upstream.status), ...(data?.cookie ? { punchout: String(data.cookie) } : {}) });
  }
  return back(request, { punchout: String(data.cookie) });
}
