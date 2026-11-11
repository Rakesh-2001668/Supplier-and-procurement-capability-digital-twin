import { NextRequest, NextResponse } from 'next/server';
import { legacyDemoAllowed } from '@/lib/pic/deployment';

// Pages that work without a session: sign-in, supplier self-registration from an invitation link (F8-01), and account activation / password reset from an administrator's link.
const PUBLIC_PAGES = ['/pic/login', '/pic/register', '/pic/activate'];

// Organisation registration (buyer / supplier) and its e-mail confirmation: public in every environment.
const PUBLIC_PLATFORM_PAGES = ['/register', '/register/verify'];

// One platform, one sign-in: the earlier entry points of the Supplier Capability Digital Twin lead to the platform pages.
const ENTRY_REDIRECTS: Record<string, string> = { '/': '/pic', '/login': '/pic/login', '/signin': '/pic/login' };

function isWorkspace(pathname: string): boolean {
  return pathname === '/pic' || pathname.startsWith('/pic/');
}

function redirect(request: NextRequest, pathname: string, search = ''): NextResponse {
  const url = request.nextUrl.clone();
  url.pathname = pathname;
  url.search = search;
  return NextResponse.redirect(url);
}

function signIn(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;
  return redirect(request, '/pic/login', `?next=${encodeURIComponent(pathname + search)}`);
}

// 1. Entry points: `/`, `/login`, `/signin` → the platform pages; `/register` and `/register/verify` are public.
// 2. Twin screens (everything outside /pic): retired in production (PIC_ENV=production or NEXT_PUBLIC_PIC_ENV=production, unless
//    PIC_ENABLE_LEGACY_DEMO=true): they redirect to /pic. Where they are on, they need the platform session like every other page.
// 3. PIC workspace: no session cookie → sign-in page.
//    Authorisation itself is enforced by the API on every call (scopes, ABAC, SoD, RLS).
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const entry = ENTRY_REDIRECTS[pathname];
  if (entry) return redirect(request, entry);
  if (PUBLIC_PLATFORM_PAGES.includes(pathname)) return NextResponse.next();
  if (!isWorkspace(pathname)) {
    if (!legacyDemoAllowed()) return redirect(request, '/pic');
    return request.cookies.get('pic_session') ? NextResponse.next() : signIn(request);
  }
  if (PUBLIC_PAGES.includes(pathname)) return NextResponse.next();
  if (!request.cookies.get('pic_session')) return signIn(request);
  return NextResponse.next();
}

export const config = {
  // Every page route; API routes (/api/*: the BFF, sign-in and health), Next.js assets and files with an extension are not gated.
  matcher: ['/((?!api/|_next/|favicon\\.ico|.*\\.[A-Za-z0-9]+$).*)'],
};
