'use client';

import { ReactNode } from 'react';
import { ProblemBox } from '@/components/pic/ui';
import type { ApiError } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';

/** "2026-09" → "Sep 2026" */
export function period(p: string | null | undefined): string {
  if (!p || p.length < 7) return p ?? '–';
  const d = new Date(Number(p.slice(0, 4)), Number(p.slice(5, 7)) - 1, 1);
  return d.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });
}

export function periodRange(periods: [string, string] | string[] | undefined): string {
  return periods && periods.length === 2 ? `${period(periods[0])} – ${period(periods[1])}` : '–';
}

export const pct = (v: string | number | null | undefined) => (v === null || v === undefined || v === '' ? '–' : `${v}%`);

/** Axis ticks in rupees (values already divided by 100). */
export const rupeeTick = (v: number) => (Math.abs(v) >= 1e7 ? `₹${(v / 1e7).toFixed(1)} Cr` : Math.abs(v) >= 1e5 ? `₹${(v / 1e5).toFixed(1)} L` : `₹${Math.round(v)}`);

/** Problem box plus, for 403, the permission that is missing. */
export function SpendProblem({ error, permission = 'spend:read' }: { error: ApiError | null | undefined; permission?: string }) {
  if (!error) return null;
  return (
    <div className="space-y-2">
      <ProblemBox error={error} />
      {error.status === 403 && (
        <p className="text-sm text-slate-600">
          This view needs the <span className="font-mono">{permission}</span> permission, held by category managers, finance controllers,
          the procurement head and the CPO. Ask your tenant administrator if you need access.
        </p>
      )}
    </div>
  );
}

/** Horizontal share bar; the number is always shown as text next to it. */
export function ShareBar({ value, max = 100, label: text }: { value: number; max?: number; label?: ReactNode }) {
  const width = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div className="flex min-w-[140px] items-center gap-2">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100" aria-hidden>
        <div className="h-full rounded-full bg-[#1A56DB]" style={{ width: `${width}%` }} />
      </div>
      <span className="w-14 text-right text-xs tabular-nums text-slate-700">{text ?? `${value.toFixed(1)}%`}</span>
    </div>
  );
}

const LEVEL_TONE: Record<string, string> = {
  HIGH: 'bg-red-50 text-red-800 ring-red-200',
  CRITICAL: 'bg-red-50 text-red-800 ring-red-200',
  MODERATE: 'bg-amber-50 text-amber-800 ring-amber-200',
  MEDIUM: 'bg-amber-50 text-amber-800 ring-amber-200',
  LOW: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
};

/** Level / severity chip (text plus colour, never colour alone). */
export function LevelChip({ level }: { level: string | null | undefined }) {
  const s = (level ?? '').toUpperCase();
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset ${LEVEL_TONE[s] ?? 'bg-slate-50 text-slate-700 ring-slate-200'}`}>
      {s || '–'}
    </span>
  );
}

export function ChartBox({ height, children, label: name }: { height: number; children: ReactNode; label: string }) {
  return <div style={{ height }} role="img" aria-label={name}>{children}</div>;
}

// ---------------------------------------------------------------- cube freshness and scope (shared by the cube, drill and quality views)
export type CubeState = {
  asOf: string | null; mode: string | null; durationMs: number | null; summaryRows: number; dirtyPeriods: string[]; pendingEvents: number; feedBehind: boolean; stale: boolean;
};

/** `GET /spend/cube-status`: when the cube was built, which periods wait and how many invoice events the consumer has not read yet. */
export function CubeStatus({ state, scope }: { state: CubeState | undefined; scope?: Record<string, unknown> | null }) {
  if (!state) return null;
  const waiting = state.dirtyPeriods.length;
  const tone = state.feedBehind || state.stale ? 'border-amber-300 bg-amber-50 text-amber-900' : 'border-slate-200 bg-white text-slate-600';
  return (
    <div className={`rounded-lg border px-4 py-2 text-xs ${tone}`} role="status" data-testid="cube-status">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <span>
          <strong className="font-semibold">Cube as of {state.asOf ? dateTime(state.asOf) : 'never built'}</strong>
          {state.mode ? ` · ${label(state.mode).toLowerCase()} refresh` : ''}{state.durationMs != null ? ` · ${state.durationMs} ms` : ''}
          {` · ${state.summaryRows.toLocaleString('en-IN')} summary rows`}
        </span>
        <span>
          {waiting ? `${waiting} period${waiting === 1 ? '' : 's'} waiting for refresh (${state.dirtyPeriods.slice(0, 4).join(', ')}${waiting > 4 ? ', …' : ''})` : 'no period waiting'}
          {' · '}{state.pendingEvents} invoice event{state.pendingEvents === 1 ? '' : 's'} not yet in the cube
        </span>
      </div>
      {state.feedBehind && <p className="mt-1 font-medium">The feed is behind: posted invoices and notes are still being relayed, so the totals do not yet include them.</p>}
      <p className="mt-1">
        {scope && Object.keys(scope).length
          ? <>Scope applied to every figure on this screen: {Object.entries(scope).map(([k, v]) => `${label(k)} ${Array.isArray(v) ? v.join(', ') : String(v)}`).join(' · ')}.</>
          : 'Scope: no restriction applies to you; figures cover the whole tenant.'}
      </p>
    </div>
  );
}

/** Drill target: the lines screen for a slice (`?tab=lines&category=...`). */
export function linesHref(filters: Record<string, string | undefined>): string {
  const q = new URLSearchParams({ tab: 'lines' });
  for (const [k, v] of Object.entries(filters)) if (v) q.set(k, v);
  return `/pic/spend?${q.toString()}`;
}

/** A change in percent with an arrow and a screen-reader word (never colour alone); `null` means there is no base to compare with. */
export function ChangePct({ value, goodWhenDown = true }: { value: string | null | undefined; goodWhenDown?: boolean }) {
  if (value === null || value === undefined) return <span className="text-slate-500">n/a</span>;
  const n = Number(value);
  const bad = goodWhenDown ? n > 0 : n < 0;
  const good = goodWhenDown ? n < 0 : n > 0;
  return (
    <span className={`font-medium tabular-nums ${bad ? 'text-amber-700' : good ? 'text-emerald-700' : 'text-slate-600'}`}>
      <span aria-hidden>{n > 0 ? '▲ ' : n < 0 ? '▼ ' : ''}</span>{n > 0 ? '+' : ''}{value}%
      <span className="sr-only">{n > 0 ? ' increase' : n < 0 ? ' decrease' : ' no change'}</span>
    </span>
  );
}

/** Fiscal years ("2026-27") counted back from a given one. */
export function fiscalYearsBack(fy: string | undefined, count = 4): string[] {
  const start = Number((fy ?? '').slice(0, 4));
  if (!start) return [];
  return Array.from({ length: count }, (_, i) => `${start - i}-${String((start - i + 1) % 100).padStart(2, '0')}`);
}

/** Inline link style for table rows. */
export const linkClass = 'font-medium text-[#1A56DB] hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1A56DB]';
