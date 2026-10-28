import { NextRequest, NextResponse } from 'next/server';
import { legacyDemoAllowed } from '@/lib/pic/deployment';

// Pages that work without a session: sign-in, and supplier self-registration from an invitation link (F8-01).
const PUBLIC_PAGES = ['/pic/login', '/pic/register'];

function isWorkspace(pathname: string): boolean {
  return pathname === '/pic' || pathname.startsWith('/pic/');
}

// 1. Legacy gate: the earlier prototype screens (everything outside /pic) are retired in production
//    (PIC_ENV=production or NEXT_PUBLIC_PIC_ENV=production, unless PIC_ENABLE_LEGACY_DEMO=true): they redirect to /pic.
// 2. Route guard for the PIC workspace: no session cookie → sign-in page.
//    Authorisation itself is enforced by the API on every call (scopes, ABAC, SoD, RLS).
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (!isWorkspace(pathname)) {
    if (legacyDemoAllowed()) return NextResponse.next();
    const url = request.nextUrl.clone();
    url.pathname = '/pic';
    url.search = '';
    return NextResponse.redirect(url);
  }
  if (PUBLIC_PAGES.includes(pathname)) return NextResponse.next();
  if (!request.cookies.get('pic_session')) {
    const url = request.nextUrl.clone();
    url.pathname = '/pic/login';
    url.search = `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // Every page route; API routes (/api/*: the BFF, sign-in and health), Next.js assets and files with an extension are not gated.
  matcher: ['/((?!api/|_next/|favicon\\.ico|.*\\.[A-Za-z0-9]+$).*)'],
};
