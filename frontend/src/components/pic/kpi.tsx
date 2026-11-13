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

const TONE: Record<string, { ring: string; text: string; word: string; badge: string; dot: string }> = {
  GOOD: {
    ring: 'from-emerald-400 to-teal-400',
    text: 'text-emerald-700 dark:text-emerald-400',
    word: 'On target',
    badge: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20',
    dot: 'bg-emerald-500',
  },
  WARN: {
    ring: 'from-amber-400 to-orange-400',
    text: 'text-amber-700 dark:text-amber-400',
    word: 'Watch',
    badge: 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20',
    dot: 'bg-amber-500',
  },
  BAD: {
    ring: 'from-red-400 to-rose-400',
    text: 'text-red-700 dark:text-red-400',
    word: 'Off target',
    badge: 'bg-red-500/10 text-red-700 dark:text-red-400 border border-red-500/20',
    dot: 'bg-red-500',
  },
  NA: {
    ring: 'from-slate-300 to-slate-400',
    text: 'text-ink',
    word: 'No target',
    badge: 'bg-surface-3 text-ink-3 border border-line',
    dot: 'bg-ink-3',
  },
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
  const step = 64 / (points.length - 1);
  const path = points.map((v, i) => (v === null ? null : `${(i * step).toFixed(1)},${(18 - ((v - min) / span) * 14).toFixed(1)}`)).filter(Boolean).join(' ');
  return (
    <div className="relative flex items-center" title={`${name} historical trend`}>
      <svg viewBox="0 0 64 22" className="h-5 w-16 text-brand-ink transition-transform duration-200 group-hover:scale-110" aria-hidden>
        <polyline points={path} fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="sr-only">{name} trend over {points.length} months: {values.map((v) => v.toLocaleString('en-IN', { maximumFractionDigits: 1 })).join(', ')}</span>
    </div>
  );
}

export function KpiCard({ item }: { item: KpiItem }) {
  const tone = TONE[item.status] ?? TONE.NA;
  const target = kpiTarget(item);
  const href = `/pic/kpis?module=${item.module}#${encodeURIComponent(item.code)}`;

  return (
    <Link
      href={href}
      title={`${item.name} (${item.formula || item.code})`}
      className="group relative flex h-full flex-col justify-between overflow-hidden rounded-2xl border border-line-strong/80 ring-1 ring-inset ring-black/[0.04] dark:ring-white/[0.06] bg-surface p-4 shadow-card transition-all duration-200 hover:-translate-y-1 hover:border-brand/60 hover:ring-brand/30 hover:shadow-raised focus:outline-none focus-visible:ring-2 focus-visible:ring-brand"
    >
      <span aria-hidden className={`absolute inset-x-0 top-0 h-[3.5px] bg-gradient-to-r opacity-85 transition-all group-hover:opacity-100 group-hover:h-[4px] ${tone.ring}`} />

      <div>
        <div className="flex items-center justify-between gap-1.5">
          <p className="text-[11px] font-bold uppercase tracking-wider text-ink-3 transition-colors group-hover:text-brand-ink">
            {item.name}
          </p>
          <span className="text-xs font-semibold text-ink-3 opacity-0 transition-all group-hover:opacity-100 group-hover:text-brand-ink group-hover:translate-x-0.5" aria-hidden>
            ↗
          </span>
        </div>
        <div className="mt-2.5 flex items-end justify-between gap-2">
          <p className={`text-[28px] font-extrabold leading-none tracking-tight tabular-nums ${tone.text}`}>
            {kpiValue(item)}
          </p>
          <Sparkline name={item.name} points={(item.trend ?? []).map((t) => (t.value === null ? null : Number(t.value)))} />
        </div>
      </div>

      <div className="mt-3.5 flex flex-wrap items-center justify-between gap-1.5 border-t border-line/60 pt-2.5 text-[11px]">
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-bold ${tone.badge}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} aria-hidden />
          <span>{item.value === null ? 'Pending' : tone.word}</span>
        </span>
        {target && (
          <span className="font-mono text-ink-3 tabular-nums font-medium">
            {target}
          </span>
        )}
      </div>
    </Link>
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
