'use client';

import Link from 'next/link';
import { MitigationRequest, Offer, offerOf } from './sod-mitigation';
import { KeyboardEvent, ReactNode, useEffect, useId, useRef, useState } from 'react';
import type { ApiError } from '@/lib/pic/api';
import { label } from '@/lib/pic/format';
import { ModuleKpis } from './kpi';

// ---------------------------------------------------------------- status chip (colour + text, never colour alone)
const DONE = ['APPROVED', 'ACTIVE', 'PAID', 'POSTED', 'CONFIRMED', 'QUALIFIED', 'PREFERRED', 'COMPLETED', 'ACCEPTED', 'VALIDATED', 'AWARDED',
  'RECEIVED', 'MATCHED', 'ORDERED', 'CONVERTED', 'SYNCED_TO_ERP', 'CLOSED', 'INVOICED', 'RESOLVED', 'VALID', 'OK', 'SIMULATED', 'REALISING',
  'CONTRACTED', 'NEGOTIATED', 'READY', 'RECONCILED', 'CREDITED', 'RECORDED'];
const ATTENTION = ['IN_APPROVAL', 'EXCEPTION', 'OPEN', 'PENDING', 'PENDING_CALLBACK', 'PENDING_APPROVAL', 'SUBMITTED', 'QUALITY_HOLD',
  'UNDER_EVALUATION', 'AWARD_PENDING', 'CONDITIONAL', 'DUPLICATE_BLOCKED', 'RETURNED', 'EXPIRING', 'UNDER_QUALIFICATION', 'IN_STEWARDSHIP',
  'RETRY', 'PARTIALLY_RECEIVED', 'PARTIALLY_ORDERED', 'IN_NEGOTIATION', 'OUT_FOR_SIGNATURE', 'FIRMED', 'IDENTIFIED', 'DUPLICATE_CHECK',
  'MATCHING', 'ACTIVE_STEP', 'OVERDUE', 'SOURCING_REQUIRED', 'AMBIGUOUS', 'AMOUNT_MISMATCH', 'UNMATCHED', 'NO_REFERENCE', 'FILE_NOT_SENT',
  'SHORT_DEPOSITED', 'EXCESS_DEPOSITED', 'ACCRUED', 'PARTIALLY_PAID'];
const BLOCKED = ['REJECTED', 'BLOCKED', 'CANCELLED', 'DEAD_LETTER', 'EXPIRED', 'PARTIALLY_REJECTED', 'TERMINATED', 'EXITED', 'LOST',
  'DELETED', 'REVERSED', 'BROKEN', 'FAILED', 'CONFLICT', 'VOID'];

export function StatusChip({ status }: { status: string | null | undefined }) {
  const s = (status ?? '').toUpperCase();
  const [tone, dot] = DONE.includes(s) ? ['bg-emerald-50 text-emerald-800 ring-emerald-200', 'bg-emerald-500']
    : ATTENTION.includes(s) ? ['bg-amber-50 text-amber-800 ring-amber-200', 'bg-amber-500']
      : BLOCKED.includes(s) ? ['bg-red-50 text-red-800 ring-red-200', 'bg-red-500']
        : ['bg-blue-50 text-blue-800 ring-blue-200', 'bg-blue-500'];
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset ${tone}`}>
      {s && <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${dot}`} />}
      {s ? s.replace(/_/g, ' ') : '–'}
    </span>
  );
}

// ---------------------------------------------------------------- layout
export function PageHeader({ eyebrow, title, subtitle, actions, kpis }: { eyebrow?: string; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; kpis?: string }) {
  return (
    <>
      <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          {eyebrow && (
            <p className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface/70 px-2.5 py-0.5 font-mono text-[11px] uppercase tracking-wider text-brand-ink">
              <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-gradient-to-br from-brand to-accent" />{eyebrow}
            </p>
          )}
          <h1 className="mt-2 text-[26px] font-semibold leading-tight tracking-tight text-ink">{title}</h1>
          {subtitle && <div className="mt-1.5 max-w-3xl text-sm leading-relaxed text-ink-2">{subtitle}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {kpis && <ModuleKpis module={kpis} />}
    </>
  );
}

export function Card({ title, actions, children, className = '' }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl border border-line bg-surface shadow-card ${className}`}>
      {(title || actions) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3.5">
          {title && <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>}
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </div>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Kpi({ label: name, value, hint, tone = 'default' }: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'default' | 'good' | 'warn' | 'bad' }) {
  const color = tone === 'good' ? 'text-emerald-700' : tone === 'warn' ? 'text-amber-700' : tone === 'bad' ? 'text-red-700' : 'text-ink';
  const bar = tone === 'good' ? 'from-emerald-400 to-teal-400' : tone === 'warn' ? 'from-amber-400 to-orange-400' : tone === 'bad' ? 'from-red-400 to-rose-400' : 'from-brand to-accent';
  return (
    <div className="relative overflow-hidden rounded-2xl border border-line bg-surface px-4 pb-3.5 pt-4 shadow-card transition hover:-translate-y-0.5 hover:shadow-raised">
      <span aria-hidden className={`absolute inset-x-0 top-0 h-[3px] bg-gradient-to-r ${bar} opacity-80`} />
      <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">{name}</p>
      <p className={`mt-1.5 text-[26px] font-semibold leading-none tracking-tight tabular-nums ${color}`}>{value ?? '–'}</p>
      {hint && <p className="mt-2 text-xs text-ink-3">{hint}</p>}
    </div>
  );
}

export function Facts({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm md:grid-cols-4">
      {items.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-xs text-ink-3">{k}</dt>
          <dd className="mt-0.5 break-words font-medium text-ink">{v ?? '–'}</dd>
        </div>
      ))}
    </dl>
  );
}

// ---------------------------------------------------------------- buttons and forms
type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost'; busy?: boolean };

export function Button({ variant = 'secondary', busy, children, className = '', disabled, ...rest }: ButtonProps) {
  const styles = {
    primary: 'bg-gradient-to-b from-brand to-brand-strong text-white shadow-sm shadow-blue-900/20 hover:brightness-110 border-transparent',
    secondary: 'bg-surface text-ink hover:bg-surface-3 border-line-strong shadow-sm',
    danger: 'bg-surface text-red-700 hover:bg-red-50 border-red-300',
    ghost: 'bg-transparent text-ink-2 hover:bg-surface-3 hover:text-ink border-transparent',
  }[variant];
  return (
    <button
      {...rest}
      aria-busy={busy || undefined}
      disabled={disabled || busy}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition active:scale-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 focus-visible:ring-offset-canvas disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100 ${styles} ${className}`}
    >
      {busy && <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />}
      {children}
    </button>
  );
}

export function LinkButton({ href, children, variant = 'secondary' }: { href: string; children: ReactNode; variant?: 'primary' | 'secondary' }) {
  const styles = variant === 'primary'
    ? 'bg-gradient-to-b from-brand to-brand-strong text-white shadow-sm shadow-blue-900/20 hover:brightness-110 border-transparent'
    : 'bg-surface text-ink hover:bg-surface-3 border-line-strong shadow-sm';
  return <Link href={href} className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition active:scale-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-brand ${styles}`}>{children}</Link>;
}

/** Labelled form field. The render function gets the input id and the id of the hint/error text for `aria-describedby`. */
export function Field({ label: name, hint, error, required, children }: {
  label: string; hint?: string; error?: string; required?: boolean; children: (id: string, describedBy?: string) => ReactNode;
}) {
  const id = useId();
  const noteId = `${id}-note`;
  const note = error ?? hint;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-ink-2">
        {name}{required && <span aria-hidden className="text-red-600"> *</span>}{required && <span className="sr-only"> (required)</span>}
      </label>
      {children(id, note ? noteId : undefined)}
      {note && <p id={noteId} role={error ? 'alert' : undefined} className={`text-xs ${error ? 'text-red-700' : 'text-ink-3'}`}>{note}</p>}
    </div>
  );
}

export const inputClass = 'w-full rounded-lg border border-line-strong bg-surface px-3 py-1.5 text-sm text-ink shadow-sm placeholder:text-ink-3 transition focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15';

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${inputClass} ${props.className ?? ''}`} />;
}

export function Select({ options, ...props }: React.SelectHTMLAttributes<HTMLSelectElement> & { options: { value: string; label: string }[] }) {
  return (
    <select {...props} className={`${inputClass} ${props.className ?? ''}`}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${inputClass} min-h-[72px] ${props.className ?? ''}`} />;
}

// ---------------------------------------------------------------- feedback
export function ProblemBox({ error }: { error: ApiError | Error | null | undefined }) {
  if (!error) return null;
  const p = (error as ApiError).problem;
  return (
    <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
      <p className="font-semibold">{p?.title ? label(String(p.title)) : 'Could not load this'}</p>
      <p className="mt-0.5">{p?.detail ?? error.message}</p>
      {(p?.ruleRef || p?.traceId) && <p className="mt-1 font-mono text-[11px] opacity-70">{[p.ruleRef && `Rule ${p.ruleRef}`, p.traceId && `Trace ${p.traceId}`].filter(Boolean).join(' · ')}</p>}
      {offerOf(error) && <MitigationRequest offer={offerOf(error) as Offer} />}
    </div>
  );
}

export function Loading({ text = 'Loading…' }: { text?: string }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-10 text-sm text-ink-3" role="status" aria-live="polite" aria-busy="true">
      <span aria-hidden className="h-4 w-4 animate-spin rounded-full border-2 border-brand/30 border-t-brand" />
      {text}
    </div>
  );
}

export function Empty({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-line-strong bg-surface-2/60 px-6 py-12 text-center">
      <span aria-hidden className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-brand-soft text-brand-ink">
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M4 7h16M4 12h10M4 17h7" strokeLinecap="round" /></svg>
      </span>
      <p className="text-sm font-medium text-ink">{title}</p>
      {hint && <p className="mt-1 text-sm text-ink-3">{hint}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- data table
export type Column<T> = { key: string; header: string; render?: (row: T) => ReactNode; align?: 'left' | 'right'; className?: string };

/** Row selection for bulk actions: the table renders a checkbox column (with a select-all in the header). */
export type Selection = { selected: ReadonlySet<string>; onChange: (next: Set<string>) => void; rowId: (row: never) => string; label?: (row: never) => string };

export function DataTable<T extends Record<string, unknown>>({ columns, rows, rowHref, loading, error, empty = 'Nothing here yet', onLoadMore, hasMore, loadingMore, caption, selection }: {
  columns: Column<T>[]; rows: T[]; rowHref?: (row: T) => string; loading?: boolean; error?: ApiError | null; empty?: string;
  onLoadMore?: () => void; hasMore?: boolean; loadingMore?: boolean; caption?: string; selection?: Selection;
}) {
  if (error) return <ProblemBox error={error} />;
  if (loading) return <Loading />;
  if (!rows.length) return <Empty title={empty} />;
  const idOf = selection ? (row: T) => (selection.rowId as (r: T) => string)(row) : null;
  const nameOf = (row: T) => (selection?.label ? (selection.label as (r: T) => string)(row) : (idOf?.(row) ?? ''));
  const allSelected = !!idOf && rows.every((r) => selection!.selected.has(idOf(r)));
  const someSelected = !!idOf && rows.some((r) => selection!.selected.has(idOf(r)));
  return (
    <div>
      <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-card">
        <table className="min-w-full divide-y divide-line text-sm">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead className="bg-surface-2">
            <tr>
              {selection && idOf && (
                <th scope="col" className="w-8 px-3 py-2">
                  <input type="checkbox" className="accent-brand" aria-label="Select all rows" checked={allSelected}
                    ref={(el) => { if (el) el.indeterminate = !allSelected && someSelected; }}
                    onChange={() => selection.onChange(allSelected ? new Set() : new Set(rows.map(idOf)))} />
                </th>
              )}
              {columns.map((c) => (
                <th key={c.key} scope="col" className={`whitespace-nowrap px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-ink-3 ${c.align === 'right' ? 'text-right' : 'text-left'}`}>{c.header}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line bg-surface">
            {rows.map((row, i) => (
              <tr key={String(row.id ?? row.number ?? i)} className={`transition-colors ${rowHref ? 'hover:bg-brand-soft' : 'hover:bg-surface-2'}`} aria-selected={selection && idOf ? selection.selected.has(idOf(row)) : undefined}>
                {selection && idOf && (
                  <td className="px-3 py-2 align-top">
                    <input type="checkbox" className="accent-brand" aria-label={`Select ${nameOf(row)}`} checked={selection.selected.has(idOf(row))}
                      onChange={() => {
                        const next = new Set(selection.selected);
                        if (next.has(idOf(row))) next.delete(idOf(row)); else next.add(idOf(row));
                        selection.onChange(next);
                      }} />
                  </td>
                )}
                {columns.map((c, ci) => {
                  const content = c.render ? c.render(row) : (row[c.key] as ReactNode) ?? '–';
                  return (
                    <td key={c.key} className={`px-3 py-2.5 align-top text-ink ${c.align === 'right' ? 'text-right tabular-nums' : ''} ${c.className ?? ''}`}>
                      {rowHref && ci === 0 ? <Link href={rowHref(row)} prefetch={false} className="font-medium text-brand-ink hover:underline">{content}</Link> : content}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hasMore && onLoadMore && (
        <div className="mt-3 text-center"><Button onClick={onLoadMore} busy={loadingMore}>Load more</Button></div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- tabs and dialog
/** WAI-ARIA tabs: arrow keys, Home and End move between tabs (roving tabindex); each tab controls its panel. */
export function Tabs({ tabs, label: name = 'Sections' }: { tabs: { id: string; label: ReactNode; content: ReactNode }[]; label?: string }) {
  const base = useId();
  const [active, setActive] = useState(tabs[0]?.id);
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const current = tabs.find((t) => t.id === active) ?? tabs[0];
  function onKey(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    const move = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    const to = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : move ? (index + move + tabs.length) % tabs.length : -1;
    if (to < 0) return;
    e.preventDefault();
    refs.current[to]?.focus();
    setActive(tabs[to].id);
  }
  return (
    <div>
      <div role="tablist" aria-label={name} className="flex flex-wrap gap-1 border-b border-line">
        {tabs.map((t, i) => {
          const on = current?.id === t.id;
          return (
            <button key={t.id} ref={(el) => { refs.current[i] = el; }} id={`${base}-tab-${t.id}`} role="tab" type="button" aria-selected={on}
              aria-controls={`${base}-panel`} tabIndex={on ? 0 : -1} onClick={() => setActive(t.id)} onKeyDown={(e) => onKey(e, i)}
              className={`-mb-px rounded-t-lg border-b-2 px-3.5 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand ${on ? 'border-brand text-brand-ink' : 'border-transparent text-ink-3 hover:bg-surface-3/60 hover:text-ink'}`}>
              {t.label}
            </button>
          );
        })}
      </div>
      <div className="pt-4" role="tabpanel" id={`${base}-panel`} aria-labelledby={current ? `${base}-tab-${current.id}` : undefined} tabIndex={0}>{current?.content}</div>
    </div>
  );
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Modal dialog: labelled by its title, focus moves in and is trapped while open, Escape closes, focus returns to the opener. */
export function Dialog({ open, title, onClose, children, wide = false }: { open: boolean; title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const first = panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel.current)?.focus();
    return () => opener?.focus?.();
  }, [open]);
  if (!open) return null;
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape') { e.stopPropagation(); onClose(); return; }
    if (e.key !== 'Tab' || !panel.current) return;
    const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
  return (
    <div className="fixed inset-0 z-40 flex animate-fade items-start justify-center overflow-y-auto bg-[#0B1020]/50 p-4 pt-16 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby={titleId}
      onKeyDown={onKeyDown}>
      <div ref={panel} tabIndex={-1} className={`w-full ${wide ? 'max-w-5xl' : 'max-w-2xl'} animate-pop rounded-2xl border border-line bg-surface text-ink shadow-raised focus:outline-none`}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 id={titleId} className="text-base font-semibold tracking-tight">{title}</h2>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-ink-3 hover:bg-surface-3 hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-brand" aria-label="Close dialog">✕</button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- lifecycle strip (BP 6.1): where the user is in the 14-stage chain
export const LIFECYCLE: { id: string; label: string; href: string; paths: string[] }[] = [
  { id: 'plan', label: 'Plan', href: '/pic/mrp', paths: ['/pic/mrp'] },
  { id: 'request', label: 'Request', href: '/pic/requisitions', paths: ['/pic/requisitions', '/pic/buyer'] },
  { id: 'approve', label: 'Approve', href: '/pic/tasks', paths: ['/pic/tasks'] },
  { id: 'source', label: 'Source', href: '/pic/sourcing', paths: ['/pic/sourcing'] },
  { id: 'award', label: 'Award', href: '/pic/sourcing', paths: [] },
  { id: 'contract', label: 'Contract', href: '/pic/contracts', paths: ['/pic/contracts'] },
  { id: 'order', label: 'Order', href: '/pic/purchase-orders', paths: ['/pic/purchase-orders'] },
  { id: 'confirm', label: 'Confirm', href: '/pic/purchase-orders/changes', paths: ['/pic/purchase-orders/changes', '/pic/purchase-orders/expediting'] },
  { id: 'receive', label: 'Receive', href: '/pic/receiving', paths: ['/pic/receiving', '/pic/inventory'] },
  { id: 'inspect', label: 'Inspect', href: '/pic/receiving', paths: [] },
  { id: 'invoice', label: 'Invoice', href: '/pic/invoices', paths: ['/pic/invoices'] },
  { id: 'match', label: 'Match & post', href: '/pic/invoices/reconciliation', paths: ['/pic/invoices/reconciliation'] },
  { id: 'pay', label: 'Pay', href: '/pic/invoices/insights', paths: ['/pic/invoices/insights'] },
  { id: 'realise', label: 'Realise savings', href: '/pic/savings', paths: ['/pic/savings', '/pic/spend'] },
];

/** The stage a workspace path belongs to (the longest matching path wins), or null outside the chain. */
export function lifecycleStage(pathname: string | null | undefined): string | null {
  let best: { id: string; length: number } | null = null;
  for (const stage of LIFECYCLE) {
    for (const p of stage.paths) {
      if ((pathname === p || pathname?.startsWith(`${p}/`)) && (!best || p.length > best.length)) best = { id: stage.id, length: p.length };
    }
  }
  return best?.id ?? null;
}

export function LifecycleStrip({ pathname }: { pathname: string | null | undefined }) {
  const current = lifecycleStage(pathname);
  return (
    <nav aria-label="Procurement lifecycle" className="border-t border-line bg-surface/80 px-4 py-2.5 backdrop-blur md:px-8">
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-1 text-[11px]">
        {LIFECYCLE.map((stage, i) => {
          const on = stage.id === current;
          return (
            <li key={stage.id} className="flex items-center gap-1">
              <Link href={stage.href} prefetch={false} aria-current={on ? 'step' : undefined}
                className={`rounded-full px-2.5 py-0.5 font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand ${on ? 'bg-gradient-to-r from-brand to-accent text-white shadow-sm' : 'bg-surface-3 text-ink-2 hover:bg-brand-soft hover:text-brand-ink'}`}>
                <span className="font-mono opacity-70">{i + 1}</span> {stage.label}
              </Link>
              {i < LIFECYCLE.length - 1 && <span aria-hidden className="text-line-strong">›</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
