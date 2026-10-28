import { NextRequest } from 'next/server';
import { apiBase, clientIp, SESSION_COOKIE } from '@/lib/pic/server';

// Forwards /api/pic/v1/... to the PIC API with the session token attached.
// Streams the response body so the server-sent event stream (/v1/stream) passes through.

const FORWARD_REQUEST_HEADERS = ['content-type', 'idempotency-key', 'if-match', 'x-request-id', 'accept', 'traceparent', 'tracestate'];
const FORWARD_RESPONSE_HEADERS = ['content-type', 'content-disposition', 'etag', 'x-request-id', 'retry-after', 'cache-control', 'traceparent'];

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (path[0] !== 'v1') {
    return Response.json({ code: 'NOT_FOUND', detail: 'Unknown API path' }, { status: 404 });
  }
  const target = `${apiBase()}/${path.map(encodeURIComponent).join('/')}${request.nextUrl.search}`;
  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (token) headers.set('authorization', `Bearer ${token}`);
  const ip = clientIp(request.headers);
  if (ip) headers.set('x-forwarded-for', ip);

  const hasBody = !['GET', 'HEAD'].includes(request.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      // Raw bytes, not text: multipart uploads (invoice scans, ERP CSV imports) must pass through unchanged.
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: 'no-store',
      signal: request.signal,
    });
  } catch {
    return Response.json(
      { code: 'API_UNAVAILABLE', title: 'API_UNAVAILABLE', detail: 'The procurement API is not reachable. Check that it is running.' },
      { status: 502, headers: { 'content-type': 'application/problem+json' } },
    );
  }
  const responseHeaders = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
