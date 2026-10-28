'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { createContext, useContext, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { readSessionUser, SessionUser, signOut } from '@/lib/pic/api';
import { dateTime } from '@/lib/pic/format';
import { NotificationBell } from '@/app/pic/notifications/_notifications';
import { ToastProvider } from './toast';

type LiveEvent = { id: string; type: string; ref: string; objectType: string; actor: string; at: string };
type Live = { connected: boolean; openTasks: number | null; events: LiveEvent[] };
const LiveContext = createContext<Live>({ connected: false, openTasks: null, events: [] });
export const useLive = () => useContext(LiveContext);

type NavItem = { href: string; label: string; roles?: string[] };
const INTERNAL_NAV: { group: string; items: NavItem[] }[] = [
  { group: 'Decide', items: [
    { href: '/pic', label: 'Command centre' },
    { href: '/pic/copilot', label: 'Copilot' },
    { href: '/pic/spend', label: 'Spend', roles: ['CATEGORY_MANAGER', 'FINANCE_CONTROLLER', 'PROCUREMENT_HEAD', 'CPO'] },
    { href: '/pic/savings', label: 'Savings' },
  ] },
  { group: 'My work', items: [{ href: '/pic/tasks', label: 'Task inbox' }, { href: '/pic/notifications', label: 'Notifications' }, { href: '/pic/account', label: 'My account & security' }] },
  { group: 'Plan & request', items: [
    { href: '/pic/mrp', label: 'MRP & planning' },
    { href: '/pic/mrp/forecast', label: 'Demand forecast', roles: ['MRP_CONTROLLER', 'TENANT_ADMIN'] },
    { href: '/pic/requisitions', label: 'Requisitions' },
    { href: '/pic/buyer', label: 'Buyer workbench', roles: ['BUYER'] },
    { href: '/pic/materials', label: 'Materials & MDM' },
  ] },
  { group: 'Source & contract', items: [
    { href: '/pic/sourcing', label: 'Sourcing events' },
    { href: '/pic/contracts', label: 'Contracts' },
    { href: '/pic/contracts/obligations', label: 'Obligations & renewals' },
    { href: '/pic/suppliers', label: 'Suppliers' },
    { href: '/pic/suppliers/performance', label: 'Supplier performance' },
    { href: '/pic/suppliers/risk', label: 'Supplier risk' },
  ] },
  { group: 'Order to pay', items: [
    { href: '/pic/purchase-orders', label: 'Purchase orders' },
    { href: '/pic/purchase-orders/changes', label: 'Confirmations & changes' },
    { href: '/pic/purchase-orders/expediting', label: 'Expediting' },
    { href: '/pic/receiving', label: 'Receiving & quality' },
    { href: '/pic/invoices', label: 'Invoices & payments' },
    { href: '/pic/invoices/reconciliation', label: 'Posting & reconciliation', roles: ['AP_CLERK', 'FINANCE_CONTROLLER'] },
    { href: '/pic/invoices/insights', label: 'Payables insights', roles: ['AP_CLERK', 'FINANCE_CONTROLLER', 'CPO', 'PROCUREMENT_HEAD'] },
  ] },
  { group: 'Govern', items: [
    { href: '/pic/processes', label: 'Process monitor' },
    { href: '/pic/agents', label: 'AI agents' },
    { href: '/pic/admin', label: 'Administration', roles: ['TENANT_ADMIN'] },
  ] },
];
const SUPPLIER_NAV: { group: string; items: NavItem[] }[] = [{ group: 'Supplier portal', items: [{ href: '/pic/portal', label: 'Overview' }, { href: '/pic/copilot', label: 'Ask about my documents' }, { href: '/pic/notifications', label: 'Notifications' }, { href: '/pic/account', label: 'My account & security' }] }];

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
  // Sign-in and the public supplier registration page render without the workspace chrome.
  const isLogin = pathname === '/pic/login' || pathname === '/pic/register' || pathname.startsWith('/pic/register/');
  const live = useLiveStream(!isLogin && !!user);

  if (isLogin) return <ToastProvider>{children}</ToastProvider>;

  const supplier = user?.roles.includes('SUPPLIER_USER');
  const nav = (supplier ? SUPPLIER_NAV : INTERNAL_NAV).map((g) => ({
    ...g, items: g.items.filter((i) => !i.roles || i.roles.some((r) => user?.roles.includes(r))),
  })).filter((g) => g.items.length);

  return (
    <LiveContext.Provider value={live}>
      <ToastProvider>
        <div className="min-h-screen bg-[#F4F6FB] text-slate-900 md:flex">
          <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">Skip to content</a>
          <aside className={`${menuOpen ? 'block' : 'hidden'} w-full shrink-0 bg-[#0B1020] text-slate-300 md:sticky md:top-0 md:block md:h-screen md:w-60 md:overflow-y-auto`}>
            <div className="flex items-center gap-2 px-5 py-4">
              <span className="flex h-7 w-7 items-center justify-center rounded-md bg-[#1A56DB] font-bold text-white">α</span>
              <div>
                <p className="text-sm font-semibold text-white">Purchasing Intelligence</p>
                <p className="text-[11px] text-slate-400">AlphaHelion Cloud</p>
              </div>
            </div>
            <nav aria-label="Workspace" className="px-3 pb-6">
              {nav.map((g) => (
                <div key={g.group} className="mt-4">
                  <p className="px-2 text-[10px] font-semibold uppercase tracking-widest text-slate-500">{g.group}</p>
                  <ul className="mt-1 space-y-0.5">
                    {g.items.map((item) => {
                      // The most specific matching entry is active (e.g. /pic/suppliers/risk, not /pic/suppliers).
                      const matches = (href: string) => (href === '/pic' ? pathname === '/pic' : pathname === href || !!pathname?.startsWith(`${href}/`));
                      const active = matches(item.href) && !nav.some((o) => o.items.some((x) => x.href.length > item.href.length && x.href.startsWith(item.href) && matches(x.href)));
                      return (
                        <li key={item.href}>
                          <Link href={item.href} prefetch={false} onClick={() => setMenuOpen(false)} aria-current={active ? 'page' : undefined}
                            className={`flex items-center justify-between rounded-md px-2 py-1.5 text-sm ${active ? 'bg-[#1A56DB] text-white' : 'hover:bg-white/5 hover:text-white'}`}>
                            {item.label}
                            {item.href === '/pic/tasks' && !!live.openTasks && (
                              <span className="rounded-full bg-[#F59E0B] px-1.5 text-[11px] font-bold text-[#0B1020]">{live.openTasks}</span>
                            )}
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
              <div className="mt-6 border-t border-white/10 pt-3">
                <Link href="/command-centre" className="block rounded-md px-2 py-1.5 text-xs text-slate-500 hover:text-slate-300">Legacy demo screens ↗</Link>
              </div>
            </nav>
          </aside>
          <div className="min-w-0 flex-1">
            <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-slate-200 bg-white/95 px-4 py-2.5 backdrop-blur md:px-8">
              <div className="flex items-center gap-3">
                <button className="rounded p-1.5 text-slate-600 hover:bg-slate-100 md:hidden" onClick={() => setMenuOpen((o) => !o)} aria-label="Menu">☰</button>
                <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-700">{user?.tenant ?? '…'}</span>
                <span className="hidden text-xs text-slate-500 sm:inline">Manufacturing template</span>
              </div>
              <div className="flex items-center gap-4">
                <span className="flex items-center gap-1.5 text-xs text-slate-600" title={live.connected ? 'Receiving live updates' : 'Reconnecting…'}>
                  <span className={`h-2 w-2 rounded-full ${live.connected ? 'bg-emerald-500' : 'bg-slate-300'}`} aria-hidden />
                  {live.connected ? 'Live' : 'Offline'}
                </span>
                {live.events[0] && (
                  <span className="hidden max-w-xs truncate text-xs text-slate-500 lg:inline">
                    {live.events[0].type} · {live.events[0].ref} · {dateTime(live.events[0].at)}
                  </span>
                )}
                {user && <NotificationBell />}
                <Link href="/pic/account" prefetch={false} className="rounded-md px-1 text-right hover:bg-slate-50" title="My account & security">
                  <p className="text-sm font-medium leading-tight">{user?.name ?? ''}</p>
                  <p className="text-[11px] leading-tight text-slate-500">{user?.roles.map((r) => r.replace(/_/g, ' ').toLowerCase()).join(', ')}</p>
                </Link>
                <button onClick={signOut} className="rounded-md border border-slate-300 px-2.5 py-1 text-xs hover:bg-slate-50">Sign out</button>
              </div>
            </header>
            <main id="main" className="mx-auto max-w-[1400px] px-4 py-6 md:px-8">{children}</main>
          </div>
        </div>
      </ToastProvider>
    </LiveContext.Provider>
  );
}
