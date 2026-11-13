'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { createContext, useContext, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { readSessionUser, SessionUser, signOut } from '@/lib/pic/api';
import { useApi } from '@/lib/pic/hooks';
import { LifecycleStrip } from './ui';
import { legacyDemoEnabled } from '@/lib/pic/deployment';
import { dateTime } from '@/lib/pic/format';
import { NotificationBell } from '@/app/pic/notifications/_notifications';
import { ToastProvider } from './toast';
import { isTwinPage, navigationFor } from '@/components/nav/picNavigation';
import IndustrySwitcher from '@/components/layout/IndustrySwitcher';
import OrganisationSwitcher from './OrganisationSwitcher';
import ThemeToggle from '@/components/ThemeToggle';
import { LogOut } from 'lucide-react';

type LiveEvent = { id: string; type: string; ref: string; objectType: string; actor: string; at: string };
type Live = { connected: boolean; openTasks: number | null; events: LiveEvent[] };
const LiveContext = createContext<Live>({ connected: false, openTasks: null, events: [] });
export const useLive = () => useContext(LiveContext);

// Pages without the platform chrome: sign-in, account activation, and the public registration pages.
const PUBLIC_PAGES = ['/pic/login', '/pic/activate', '/pic/register', '/login', '/register', '/register/verify'];

function useLiveStream(enabled: boolean): Live {
  const client = useQueryClient();
  const [live, setLive] = useState<Live>({ connected: false, openTasks: null, events: [] });
  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let controller: AbortController | null = null;
    let retry = 1000;
    let refreshTimer: ReturnType<typeof setTimeout> | null = null;
    const connect = async () => {
      controller = new AbortController();
      try {
        const response = await fetch('/api/pic/v1/stream', { signal: controller.signal, headers: { accept: 'text/event-stream' } });
        if (!response.ok || !response.body) throw new Error(String(response.status));
        setLive((l) => ({ ...l, connected: true }));
        retry = 1000;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (!stopped) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split('\n\n');
          buffer = chunks.pop() ?? '';
          for (const chunk of chunks) {
            const event = /^event: (.+)$/m.exec(chunk)?.[1];
            const data = /^data: (.+)$/m.exec(chunk)?.[1];
            if (!event || !data) continue;
            const payload = JSON.parse(data);
            if (event === 'tasks') setLive((l) => ({ ...l, openTasks: payload.open }));
            if (event === 'domain') {
              setLive((l) => ({ ...l, events: [payload, ...l.events].slice(0, 30) }));
              // Something changed in the tenant: refresh what is on screen (debounced).
              if (refreshTimer) clearTimeout(refreshTimer);
              refreshTimer = setTimeout(() => client.invalidateQueries(), 400);
            }
          }
        }
      } catch {
        // fall through to reconnect
      }
      setLive((l) => ({ ...l, connected: false }));
      if (!stopped) setTimeout(connect, (retry = Math.min(retry * 2, 30000)));
    };
    connect();
    return () => {
      stopped = true;
      controller?.abort();
      if (refreshTimer) clearTimeout(refreshTimer);
    };
  }, [enabled, client]);
  return live;
}

const subscribeNothing = () => () => {};
const readCookies = () => document.cookie;

export default function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // The display profile cookie is read on every render on the client (it changes at sign-in), never on the server.
  const profileCookie = useSyncExternalStore(subscribeNothing, readCookies, () => '');
  const user = useMemo<SessionUser | null>(() => (profileCookie ? readSessionUser() : null), [profileCookie]);
  const [menuOpen, setMenuOpen] = useState(false);
  // Sign-in and the public registration and activation pages render without the platform chrome.
  const isLogin = PUBLIC_PAGES.includes(pathname) || pathname.startsWith('/pic/register/');
  const live = useLiveStream(!isLogin && !!user);
  const tenant = useApi<{ name: string; templateLabel: string }>(!isLogin && user ? '/tenant' : null);
  const supplier = !!user?.roles.includes('SUPPLIER_USER');
  const twinPage = isTwinPage(pathname);

  // The twin screens read their demonstration persona from the browser; the signed-in user decides it (no persona switch).
  useEffect(() => {
    if (!user || !twinPage) return;
    try {
      localStorage.setItem('app_role', supplier ? 'supplier' : 'buyer');
      localStorage.setItem('tenant_id', supplier ? 'supplier-mock' : 'buyer-mock');
    } catch {
      // storage blocked: the twin screens fall back to their buyer defaults
    }
  }, [user, supplier, twinPage]);

  if (isLogin) {
    return (
      <ToastProvider>
        <div className="fixed right-4 top-4 z-50"><ThemeToggle showLabels={false} /></div>
        {children}
      </ToastProvider>
    );
  }

  const nav = navigationFor(user?.roles ?? [], legacyDemoEnabled);

  const initials = (user?.name ?? '').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join('') || '·';
  const roles = user?.roles.map((r) => r.replace(/_/g, ' ').toLowerCase()).join(', ');

  return (
    <LiveContext.Provider value={live}>
      <ToastProvider>
        <div className="min-h-screen bg-canvas text-ink md:flex">
          <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">Skip to content</a>
          {/* The sidebar keeps its own dark design in both themes (theme-fixed: the dark-theme overrides leave it alone). */}
          <aside id="workspace-nav" aria-label="Navigation"
            className={`theme-fixed ${menuOpen ? 'block' : 'hidden'} relative w-full shrink-0 bg-gradient-to-b from-[#0B1020] via-[#0C1430] to-[#0B1020] text-slate-300 md:sticky md:top-0 md:block md:h-screen md:w-64 md:overflow-y-auto`}>
            <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-[radial-gradient(300px_140px_at_20%_0%,rgba(59,118,240,0.25),transparent_70%)]" />
            <Link href="/pic" prefetch={false} className="relative flex items-center gap-3 px-5 pb-4 pt-5 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[#3B76F0] to-[#7C3AED] text-lg font-bold text-white shadow-lg shadow-blue-900/40">α</span>
              <span>
                <span className="block text-sm font-semibold tracking-tight text-white">Purchasing Intelligence</span>
                <span className="block text-[11px] text-slate-400">AlphaHelion Cloud</span>
              </span>
            </Link>
            <nav aria-label="Workspace" className="relative px-3 pb-8">
              {nav.map((g) => (
                <div key={g.group} className={g.twin ? 'mt-6 border-t border-white/10 pt-4' : 'mt-5'}>
                  <p className={`px-3 text-[10px] font-semibold uppercase tracking-[0.14em] ${g.twin ? 'text-sky-400' : 'text-slate-500'}`}>{g.group}</p>
                  <ul className="mt-1.5 space-y-0.5">
                    {g.items.map((item) => {
                      // The most specific matching entry is active (e.g. /pic/suppliers/risk, not /pic/suppliers).
                      const matches = (href: string) => (href === '/pic' ? pathname === '/pic' : pathname === href || !!pathname?.startsWith(`${href}/`));
                      const active = matches(item.href) && !nav.some((o) => o.items.some((x) => x.href.length > item.href.length && x.href.startsWith(item.href) && matches(x.href)));
                      const Icon = item.icon;
                      return (
                        <li key={item.href}>
                          <Link href={item.href} prefetch={false} onClick={() => setMenuOpen(false)} aria-current={active ? 'page' : undefined}
                            className={`group relative flex items-center justify-between rounded-lg px-3 py-1.5 text-[13px] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${
                              active ? 'bg-white/[0.09] font-medium text-white' : 'text-slate-300 hover:bg-white/[0.05] hover:text-white'}`}>
                            {active && <span aria-hidden className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r-full bg-gradient-to-b from-[#60A5FA] to-[#A78BFA]" />}
                            <span className="flex items-center gap-2.5">
                              <Icon size={16} aria-hidden className={active ? 'text-sky-300' : 'text-slate-500 transition-colors group-hover:text-slate-300'} />
                              {item.label}
                            </span>
                            {item.href === '/pic/tasks' && !!live.openTasks && (
                              <span className="rounded-full bg-amber-400 px-1.5 text-[11px] font-bold leading-[18px] text-[#0B1020]">{live.openTasks}</span>
                            )}
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
            </nav>
          </aside>
          <div className="min-w-0 flex-1">
            <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-line bg-surface/80 px-4 py-2 backdrop-blur-xl supports-[backdrop-filter]:bg-surface/70 md:px-8">
              <div className="flex min-w-0 items-center gap-3">
                <button type="button" className="rounded-lg p-1.5 text-ink-2 hover:bg-surface-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand md:hidden" onClick={() => setMenuOpen((o) => !o)} aria-label="Menu" aria-expanded={menuOpen} aria-controls="workspace-nav">☰</button>
                {user ? <OrganisationSwitcher fallbackCode={user.tenant} /> : <span className="rounded bg-surface-3 px-2 py-0.5 font-mono text-xs text-ink-2">…</span>}
                {tenant.data && (
                  <span className="hidden truncate rounded-full border border-line bg-surface-2 px-2.5 py-0.5 text-[11px] font-medium text-ink-3 sm:inline" title={tenant.data.name}>
                    {tenant.data.templateLabel} template
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                {twinPage && legacyDemoEnabled && !supplier && <IndustrySwitcher />}
                <span className={`hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold sm:flex ${live.connected ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : 'bg-surface-3 text-ink-3'}`}
                  title={live.connected ? 'Receiving live updates' : 'Reconnecting…'}>
                  <span className="relative flex h-2 w-2" aria-hidden>
                    {live.connected && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />}
                    <span className={`relative inline-flex h-2 w-2 rounded-full ${live.connected ? 'bg-emerald-500' : 'bg-ink-3'}`} />
                  </span>
                  {live.connected ? 'Live' : 'Offline'}
                </span>
                {live.events[0] && (
                  <span className="hidden max-w-xs truncate text-xs text-ink-3 2xl:inline">
                    {live.events[0].type} · {live.events[0].ref} · {dateTime(live.events[0].at)}
                  </span>
                )}
                <ThemeToggle />
                {user && <NotificationBell />}
                <Link href="/pic/account" prefetch={false} className="flex items-center gap-2.5 rounded-xl px-1.5 py-1 hover:bg-surface-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand" title="My account & security">
                  <span aria-hidden className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#3B76F0] to-[#7C3AED] text-xs font-semibold text-white shadow-sm">{initials}</span>
                  <span className="hidden text-left lg:block">
                    <span className="block max-w-[180px] truncate text-sm font-medium leading-tight text-ink">{user?.name ?? ''}</span>
                    <span className="block max-w-[180px] truncate text-[11px] capitalize leading-tight text-ink-3">{roles}</span>
                  </span>
                </Link>
                <button onClick={signOut} title="Sign out" className="flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-xs font-medium text-ink-2 transition hover:border-line-strong hover:bg-surface-3 hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-brand">
                  <LogOut size={14} aria-hidden /><span className="hidden sm:inline">Sign out</span>
                </button>
              </div>
            </header>
            {/* Twin screens bring their own page layout and dark design (theme-fixed); PIC pages use the workspace container. */}
            {twinPage
              ? <main id="main" className="theme-fixed min-w-0">{children}</main>
              : (
                <main id="main" className="relative">
                  <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-[420px] [background:var(--glow)]" />
                  <div className="relative mx-auto max-w-[1400px] animate-rise px-4 py-6 md:px-8 md:py-8">{children}</div>
                </main>
              )}
            {!supplier && !twinPage && !user?.roles.includes('PLATFORM_OPERATOR') && <footer><LifecycleStrip pathname={pathname} /></footer>}
          </div>
        </div>
      </ToastProvider>
    </LiveContext.Provider>
  );
}
