'use client';

import Link from 'next/link';
import { useApi } from '@/lib/pic/hooks';

// KPI cards from the KPI framework (/v1/kpis, Blueprint Table 28). This file must not import ./ui (ui renders ModuleKpis).

export type KpiItem = {
  code: string; module: string; name: string; unit: string; direction: string; formula: string; source: string;
  target: number | null; warn: number | null; scopes: string[]; pointInTime: boolean; templates: string[]; period: string | null; plant: string | null;
  value: string | null; numerator: string | null; denominator: string | null; status: 'GOOD' | 'WARN' | 'BAD' | 'NA'; detail: Record<string, unknown>;
  trend?: { period: string; value: string | null; status: string }[];
};
export type KpiResponse = { period: string | null; plant: string | null; items: KpiItem[]; summary: Record<string, number> };

const TONE: Record<string, { ring: string; text: string; word: string }> = {
  GOOD: { ring: 'from-emerald-400 to-teal-400', text: 'text-emerald-700', word: 'On target' },
  WARN: { ring: 'from-amber-400 to-orange-400', text: 'text-amber-700', word: 'Watch' },
  BAD: { ring: 'from-red-400 to-rose-400', text: 'text-red-700', word: 'Off target' },
  NA: { ring: 'from-slate-300 to-slate-400', text: 'text-ink', word: 'No target' },
};

const crore = (minor: number) => (Math.abs(minor) >= 1e9 ? `₹${(minor / 1e9).toFixed(2)} Cr` : Math.abs(minor) >= 1e7 ? `₹${(minor / 1e7).toFixed(2)} L` : `₹${(minor / 100).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`);

/** The value with its unit, in Indian conventions; "–" when there is nothing to measure yet. */
export function kpiValue(item: Pick<KpiItem, 'value' | 'unit'>): string {
  if (item.value === null || item.value === undefined) return '–';
  const n = Number(item.value);
  switch (item.unit) {
    case 'PCT': return `${n.toLocaleString('en-IN', { maximumFractionDigits: 1 })}%`;
    case 'DAYS': return `${n.toLocaleString('en-IN', { maximumFractionDigits: 1 })} d`;
    case 'HOURS': return `${n.toLocaleString('en-IN', { maximumFractionDigits: 1 })} h`;
    case 'PPM': return `${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })} ppm`;
    case 'MINOR': return crore(n);
    default: return n.toLocaleString('en-IN', { maximumFractionDigits: 1 });
  }
}

export function kpiTarget(item: Pick<KpiItem, 'target' | 'direction' | 'unit'>): string | null {
  if (item.target === null || item.direction === 'INFO') return null;
  const shown = item.unit === 'MINOR' ? crore(item.target) : `${item.target}${item.unit === 'PCT' ? '%' : item.unit === 'DAYS' ? ' d' : item.unit === 'HOURS' ? ' h' : ''}`;
  return `${item.direction === 'HIGHER_BETTER' ? 'target ≥' : 'target ≤'} ${shown}`;
}

/** A small trend line from month-end snapshots; the numbers are also available as text for screen readers. */
export function Sparkline({ points, name }: { points: (number | null)[]; name: string }) {
  const values = points.filter((v): v is number => v !== null);
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = 60 / (points.length - 1);
  const path = points.map((v, i) => (v === null ? null : `${(i * step).toFixed(1)},${(16 - ((v - min) / span) * 14).toFixed(1)}`)).filter(Boolean).join(' ');
  return (
    <>
      <svg viewBox="0 0 60 18" className="h-5 w-16 text-brand-ink" aria-hidden><polyline points={path} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
      <span className="sr-only">{name} trend over {points.length} months: {values.map((v) => v.toLocaleString('en-IN', { maximumFractionDigits: 1 })).join(', ')}</span>
    </>
  );
}

export function KpiCard({ item }: { item: KpiItem }) {
  const tone = TONE[item.status] ?? TONE.NA;
  const target = kpiTarget(item);
  return (
    <div className="relative h-full overflow-hidden rounded-2xl border border-line bg-surface px-4 pb-3.5 pt-4 shadow-card transition hover:-translate-y-0.5 hover:shadow-raised">
      <span aria-hidden className={`absolute inset-x-0 top-0 h-[3px] bg-gradient-to-r opacity-80 ${tone.ring}`} />
      <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">
        <Link href={`/pic/kpis?module=${item.module}#${encodeURIComponent(item.code)}`} className="hover:text-ink hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand">{item.name}</Link>
      </p>
      <div className="mt-1.5 flex items-end justify-between gap-2">
        <p className={`text-[26px] font-semibold leading-none tracking-tight tabular-nums ${tone.text}`}>{kpiValue(item)}</p>
        <Sparkline name={item.name} points={(item.trend ?? []).map((t) => (t.value === null ? null : Number(t.value)))} />
      </div>
      <p className="mt-2 text-xs text-ink-3">
        <span className={`font-semibold ${tone.text}`}>{item.value === null ? 'Not measurable yet' : tone.word}</span>
        {target ? ` · ${target}` : ''}
      </p>
    </div>
  );
}

/** The KPI cards of one module (M01..M13) for the top of its list page. Hidden when the user cannot read KPIs. */
export function ModuleKpis({ module }: { module: string }) {
  const { data, error } = useApi<KpiResponse>(`/kpis?module=${encodeURIComponent(module)}&trend=true`);
  if (error || !data?.items.length) return null;
  return (
    <section aria-label={`${module} key performance indicators`} className="mb-6">
      <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {data.items.map((item) => <li key={item.code}><KpiCard item={item} /></li>)}
      </ul>
    </section>
  );
}
