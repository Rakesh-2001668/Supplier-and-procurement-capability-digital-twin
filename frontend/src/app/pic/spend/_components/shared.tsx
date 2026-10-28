'use client';

import { ReactNode } from 'react';
import { ProblemBox } from '@/components/pic/ui';
import type { ApiError } from '@/lib/pic/api';

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
