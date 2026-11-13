'use client';

import { useEffect, useRef, useState } from 'react';
import { Building2, Check, ChevronDown, Factory } from 'lucide-react';
import { useApi } from '@/lib/pic/hooks';

// Header switcher between the organisations this person proved at sign-in (sign-in by e-mail). Switching starts a new session in the
// chosen organisation; when its user has an authenticator, the sign-in page asks for the code first.

type Organisation = { code: string; name: string; kind: 'BUYER' | 'SUPPLIER'; current: boolean };
type Me = { tenant: string; tenantName?: string; organisations?: Organisation[] };

export default function OrganisationSwitcher({ fallbackCode }: { fallbackCode: string }) {
  const me = useApi<Me>('/me');
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const organisations = me.data?.organisations ?? [];
  const current = organisations.find((o) => o.current);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => { if (box.current && !box.current.contains(event.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  async function switchTo(code: string) {
    setBusy(code);
    setError(null);
    try {
      const response = await fetch('/api/auth/switch', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ organisation: code }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(data?.detail ?? 'The organisation could not be opened.');
        return;
      }
      if (data.mfaRequired) {
        window.location.assign('/pic/login?step=mfa');
        return;
      }
      // A full page load: every cached list belongs to the previous organisation.
      window.location.assign(data.user?.roles?.includes('SUPPLIER_USER') ? '/pic/portal' : '/pic');
    } finally {
      setBusy(null);
    }
  }

  const label = <span className="rounded bg-surface-3 px-2 py-0.5 font-mono text-xs text-ink-2" title={current?.name ?? me.data?.tenantName}>{current?.code ?? fallbackCode}</span>;
  if (organisations.length < 2) return label;

  return (
    <div className="relative" ref={box}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}
        className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs text-ink-2 hover:bg-surface-2">
        <span className="font-mono">{current?.code ?? fallbackCode}</span>
        <span className="hidden max-w-[12rem] truncate sm:inline">{current?.name}</span>
        <ChevronDown size={14} aria-hidden />
      </button>
      {open && (
        <div role="menu" className="absolute left-0 z-50 mt-1 w-72 rounded-lg border border-line bg-surface py-1 shadow-lg">
          <p className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-ink-3">Switch organisation</p>
          {organisations.map((o) => {
            const Icon = o.kind === 'SUPPLIER' ? Factory : Building2;
            return (
              <button key={o.code} type="button" role="menuitem" disabled={o.current || busy !== null} onClick={() => switchTo(o.code)}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm hover:bg-surface-2 disabled:cursor-default disabled:hover:bg-surface">
                <Icon size={16} className="shrink-0 text-brand-ink" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-ink">{o.name}</span>
                  <span className="block text-xs text-ink-3">{o.code} · {o.kind === 'SUPPLIER' ? 'Supplier' : 'Buyer'}</span>
                </span>
                {o.current && <Check size={16} className="text-emerald-600" aria-label="Current organisation" />}
                {busy === o.code && <span className="text-xs text-ink-3">Opening…</span>}
              </button>
            );
          })}
          {error && <p role="alert" className="px-3 py-2 text-xs text-red-700">{error}</p>}
        </div>
      )}
    </div>
  );
}
