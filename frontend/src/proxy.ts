import { NextRequest, NextResponse } from 'next/server';

// Route guard for the PIC workspace: no session cookie → sign-in page.
// Authorisation itself is enforced by the API on every call (scopes, ABAC, SoD, RLS).
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (pathname === '/pic/login') return NextResponse.next();
  if (!request.cookies.get('pic_session')) {
    const url = request.nextUrl.clone();
    url.pathname = '/pic/login';
    url.search = `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ['/pic', '/pic/:path*'],
};
