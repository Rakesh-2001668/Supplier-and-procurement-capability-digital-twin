'use client';

import Link from 'next/link';
import { ReactNode, useId, useState } from 'react';
import type { ApiError } from '@/lib/pic/api';
import { label } from '@/lib/pic/format';

// ---------------------------------------------------------------- status chip (colour + text, never colour alone)
const DONE = ['APPROVED', 'ACTIVE', 'PAID', 'POSTED', 'CONFIRMED', 'QUALIFIED', 'PREFERRED', 'COMPLETED', 'ACCEPTED', 'VALIDATED', 'AWARDED',
  'RECEIVED', 'MATCHED', 'ORDERED', 'CONVERTED', 'SYNCED_TO_ERP', 'CLOSED', 'INVOICED', 'RESOLVED', 'VALID', 'OK', 'SIMULATED', 'REALISING',
  'CONTRACTED', 'NEGOTIATED', 'READY'];
const ATTENTION = ['IN_APPROVAL', 'EXCEPTION', 'OPEN', 'PENDING', 'PENDING_CALLBACK', 'PENDING_APPROVAL', 'SUBMITTED', 'QUALITY_HOLD',
  'UNDER_EVALUATION', 'AWARD_PENDING', 'CONDITIONAL', 'DUPLICATE_BLOCKED', 'RETURNED', 'EXPIRING', 'UNDER_QUALIFICATION', 'IN_STEWARDSHIP',
  'RETRY', 'PARTIALLY_RECEIVED', 'PARTIALLY_ORDERED', 'IN_NEGOTIATION', 'OUT_FOR_SIGNATURE', 'FIRMED', 'IDENTIFIED', 'DUPLICATE_CHECK',
  'MATCHING', 'ACTIVE_STEP', 'OVERDUE', 'SOURCING_REQUIRED'];
const BLOCKED = ['REJECTED', 'BLOCKED', 'CANCELLED', 'DEAD_LETTER', 'EXPIRED', 'PARTIALLY_REJECTED', 'TERMINATED', 'EXITED', 'LOST',
  'DELETED', 'REVERSED', 'BROKEN', 'FAILED'];

export function StatusChip({ status }: { status: string | null | undefined }) {
  const s = (status ?? '').toUpperCase();
  const tone = DONE.includes(s) ? 'bg-emerald-50 text-emerald-800 ring-emerald-200'
    : ATTENTION.includes(s) ? 'bg-amber-50 text-amber-800 ring-amber-200'
      : BLOCKED.includes(s) ? 'bg-red-50 text-red-800 ring-red-200'
        : 'bg-blue-50 text-blue-800 ring-blue-200';
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset ${tone}`}>
      {s ? s.replace(/_/g, ' ') : '–'}
    </span>
  );
}

// ---------------------------------------------------------------- layout
export function PageHeader({ eyebrow, title, subtitle, actions }: { eyebrow?: string; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <p className="font-mono text-xs uppercase tracking-wider text-slate-500">{eyebrow}</p>}
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[#0B1020]">{title}</h1>
        {subtitle && <div className="mt-1 max-w-3xl text-sm text-slate-600">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ title, actions, children, className = '' }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white ${className}`}>
      {(title || actions) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-5 py-3">
          {title && <h2 className="text-sm font-semibold text-slate-900">{title}</h2>}
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </div>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Kpi({ label: name, value, hint, tone = 'default' }: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'default' | 'good' | 'warn' | 'bad' }) {
  const color = tone === 'good' ? 'text-emerald-700' : tone === 'warn' ? 'text-amber-700' : tone === 'bad' ? 'text-red-700' : 'text-[#0B1020]';
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{name}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value ?? '–'}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function Facts({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm md:grid-cols-4">
      {items.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-xs text-slate-500">{k}</dt>
          <dd className="mt-0.5 break-words font-medium text-slate-900">{v ?? '–'}</dd>
        </div>
      ))}
    </dl>
  );
}

// ---------------------------------------------------------------- buttons and forms
type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost'; busy?: boolean };

export function Button({ variant = 'secondary', busy, children, className = '', disabled, ...rest }: ButtonProps) {
  const styles = {
    primary: 'bg-[#1A56DB] text-white hover:bg-[#1747b8] border-transparent',
    secondary: 'bg-white text-slate-800 hover:bg-slate-50 border-slate-300',
    danger: 'bg-white text-red-700 hover:bg-red-50 border-red-300',
    ghost: 'bg-transparent text-slate-700 hover:bg-slate-100 border-transparent',
  }[variant];
  return (
    <button
      {...rest}
      disabled={disabled || busy}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1A56DB] focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
    >
      {busy && <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />}
      {children}
    </button>
  );
}

export function LinkButton({ href, children, variant = 'secondary' }: { href: string; children: ReactNode; variant?: 'primary' | 'secondary' }) {
  const styles = variant === 'primary' ? 'bg-[#1A56DB] text-white hover:bg-[#1747b8] border-transparent' : 'bg-white text-slate-800 hover:bg-slate-50 border-slate-300';
  return <Link href={href} className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium ${styles}`}>{children}</Link>;
}

export function Field({ label: name, hint, children }: { label: string; hint?: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-slate-700">{name}</label>
      {children(id)}
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export const inputClass = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-[#1A56DB] focus:outline-none focus:ring-2 focus:ring-[#1A56DB]/20';

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
    </div>
  );
}

export function Loading({ text = 'Loading…' }: { text?: string }) {
  return <p className="py-8 text-center text-sm text-slate-500" aria-busy="true">{text}</p>;
}

export function Empty({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 px-6 py-10 text-center">
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {hint && <p className="mt-1 text-sm text-slate-500">{hint}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- data table
export type Column<T> = { key: string; header: string; render?: (row: T) => ReactNode; align?: 'left' | 'right'; className?: string };

export function DataTable<T extends Record<string, unknown>>({ columns, rows, rowHref, loading, error, empty = 'Nothing here yet', onLoadMore, hasMore, loadingMore }: {
  columns: Column<T>[]; rows: T[]; rowHref?: (row: T) => string; loading?: boolean; error?: ApiError | null; empty?: string;
  onLoadMore?: () => void; hasMore?: boolean; loadingMore?: boolean;
}) {
  if (error) return <ProblemBox error={error} />;
  if (loading) return <Loading />;
  if (!rows.length) return <Empty title={empty} />;
  return (
    <div>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50">
            <tr>
              {columns.map((c) => (
                <th key={c.key} scope="col" className={`whitespace-nowrap px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500 ${c.align === 'right' ? 'text-right' : 'text-left'}`}>{c.header}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {rows.map((row, i) => (
              <tr key={String(row.id ?? row.number ?? i)} className={rowHref ? 'hover:bg-blue-50/50' : ''}>
                {columns.map((c, ci) => {
                  const content = c.render ? c.render(row) : (row[c.key] as ReactNode) ?? '–';
                  return (
                    <td key={c.key} className={`px-3 py-2 align-top ${c.align === 'right' ? 'text-right tabular-nums' : ''} ${c.className ?? ''}`}>
                      {rowHref && ci === 0 ? <Link href={rowHref(row)} prefetch={false} className="font-medium text-[#1A56DB] hover:underline">{content}</Link> : content}
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
export function Tabs({ tabs }: { tabs: { id: string; label: ReactNode; content: ReactNode }[] }) {
  const [active, setActive] = useState(tabs[0]?.id);
  return (
    <div>
      <div role="tablist" className="flex flex-wrap gap-1 border-b border-slate-200">
        {tabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={active === t.id} onClick={() => setActive(t.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${active === t.id ? 'border-[#1A56DB] text-[#1A56DB]' : 'border-transparent text-slate-600 hover:text-slate-900'}`}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="pt-4" role="tabpanel">{tabs.find((t) => t.id === active)?.content}</div>
    </div>
  );
}

export function Dialog({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 pt-16" role="dialog" aria-modal="true" aria-label={title}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}>
      <div className="w-full max-w-2xl rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <h2 className="text-base font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded p-1 text-slate-500 hover:bg-slate-100" aria-label="Close">✕</button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}
