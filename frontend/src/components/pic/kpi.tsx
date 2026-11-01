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
  GOOD: { ring: 'border-emerald-200 bg-emerald-50/40', text: 'text-emerald-700', word: 'On target' },
  WARN: { ring: 'border-amber-200 bg-amber-50/40', text: 'text-amber-700', word: 'Watch' },
  BAD: { ring: 'border-red-200 bg-red-50/40', text: 'text-red-700', word: 'Off target' },
  NA: { ring: 'border-slate-200 bg-white', text: 'text-[#0B1020]', word: 'No target' },
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
      <svg viewBox="0 0 60 18" className="h-5 w-16" aria-hidden><polyline points={path} fill="none" stroke="#1A56DB" strokeWidth="1.5" /></svg>
      <span className="sr-only">{name} trend over {points.length} months: {values.map((v) => v.toLocaleString('en-IN', { maximumFractionDigits: 1 })).join(', ')}</span>
    </>
  );
}

export function KpiCard({ item }: { item: KpiItem }) {
  const tone = TONE[item.status] ?? TONE.NA;
  const target = kpiTarget(item);
  return (
    <div className={`rounded-xl border px-4 py-3 ${tone.ring}`}>
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        <Link href={`/pic/kpis?module=${item.module}#${encodeURIComponent(item.code)}`} className="hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1A56DB]">{item.name}</Link>
      </p>
      <div className="mt-1 flex items-end justify-between gap-2">
        <p className={`text-2xl font-semibold tabular-nums ${tone.text}`}>{kpiValue(item)}</p>
        <Sparkline name={item.name} points={(item.trend ?? []).map((t) => (t.value === null ? null : Number(t.value)))} />
      </div>
      <p className="mt-0.5 text-xs text-slate-500">
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
