'use client';

import { Suspense, useCallback, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { KpiItem, KpiResponse, kpiTarget, kpiValue, Sparkline } from '@/components/pic/kpi';
import { Button, Card, Empty, Field, Input, Kpi, Loading, PageHeader, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { SavedViews } from '@/components/pic/views';
import { api } from '@/lib/pic/api';
import { label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

const MODULES = [
  ['M01', 'M01 Spend & category'], ['M02', 'M02 Planning & MRP'], ['M03', 'M03 Master data'], ['M04', 'M04 Requisitioning'], ['M05', 'M05 Sourcing'],
  ['M06', 'M06 Supplier management'], ['M07', 'M07 Contracts'], ['M08', 'M08 Purchase orders'], ['M09', 'M09 Receipt & service entry'],
  ['M10', 'M10 Invoice & finance'], ['M11', 'M11 Savings'], ['M12', 'M12 Agents & prediction'], ['M13', 'M13 Platform'], ['TEMPLATE', 'Industry template'],
];
const STATUS_TONE: Record<string, string> = { GOOD: 'COMPLETED', WARN: 'PENDING', BAD: 'REJECTED', NA: 'INFO' };
type Filters = { module: string; period: string; plant: string; allTemplates: boolean };
type Me = { roles: string[]; scopes: string[] };

function Explorer() {
  const params = useSearchParams();
  const [filters, setFilters] = useState<Filters>({ module: params.get('module') ?? '', period: '', plant: '', allTemplates: false });
  const apply = useCallback((f: Record<string, unknown>) => setFilters((cur) => ({ ...cur, ...(f as Partial<Filters>) })), []);
  const query = new URLSearchParams({ trend: 'true' });
  if (filters.module) query.set('module', filters.module);
  if (filters.period) query.set('period', filters.period);
  if (filters.plant) query.set('plant', filters.plant);
  if (filters.allTemplates) query.set('all_templates', 'true');
  const { data, isLoading, error } = useApi<KpiResponse>(`/kpis?${query.toString()}`);
  const plants = useApi<{ plants: { code: string; name: string }[] }>('/reference');
  const me = useApi<Me>('/me');
  const canSnapshot = !!me.data?.scopes.includes('admin:integration');
  const snapshot = useCommand(() => api.post<{ period: string; kpis: number }>('/admin/kpis/snapshot', { period: filters.period || undefined }),
    { success: (r) => `${r.kpis} KPIs saved for ${r.period}` });
  const [open, setOpen] = useState<string | null>(null);
  const detail = useApi<KpiItem & { history: { period: string; value: string | null; status: string; computedAt: string }[] }>(open ? `/kpis/${encodeURIComponent(open)}${filters.period ? `?period=${filters.period}` : ''}` : null);

  const grouped = MODULES.map(([id, name]) => ({ id, name, items: (data?.items ?? []).filter((i) => i.module === id) })).filter((g) => g.items.length);
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="BP Table 28 · KPI framework" title="KPI explorer"
        subtitle="Every module KPI with its formula, source and target. Values are computed from the live transactions; month-end snapshots give the trend."
        actions={canSnapshot && <Button busy={snapshot.isPending} onClick={() => snapshot.mutate()}>Save {filters.period || 'this month'} snapshot</Button>} />
      <Card title="Filters" actions={<SavedViews screen="kpis" filters={filters} onApply={apply} />}>
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Module">{(id) => <Select id={id} value={filters.module} onChange={(e) => setFilters({ ...filters, module: e.target.value })}
            options={[{ value: '', label: 'All modules' }, ...MODULES.map(([v, l]) => ({ value: v, label: l }))]} />}</Field>
          <Field label="Month" hint="Empty: all history">{(id, d) => <Input id={id} aria-describedby={d} type="month" value={filters.period} onChange={(e) => setFilters({ ...filters, period: e.target.value })} />}</Field>
          <Field label="Plant" hint="Only KPIs measured per plant">{(id, d) => <Select id={id} aria-describedby={d} value={filters.plant} onChange={(e) => setFilters({ ...filters, plant: e.target.value })}
            options={[{ value: '', label: 'Whole organisation' }, ...(plants.data?.plants ?? []).map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))]} />}</Field>
          <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" className="accent-[#1A56DB]" checked={filters.allTemplates}
            onChange={(e) => setFilters({ ...filters, allTemplates: e.target.checked })} /> Show other industry templates</label>
        </div>
      </Card>

      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : !data ? null : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="On target" value={data.summary.GOOD} tone="good" />
            <Kpi label="Watch" value={data.summary.WARN} tone="warn" />
            <Kpi label="Off target" value={data.summary.BAD} tone="bad" />
            <Kpi label="No target or no data" value={data.summary.NA} />
          </div>
          {!grouped.length && <Empty title="No KPI matches these filters" />}
          {grouped.map((g) => (
            <Card key={g.id} title={g.name}>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <caption className="sr-only">{g.name} KPIs</caption>
                  <thead><tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                    <th scope="col" className="py-1 pr-4">KPI</th><th scope="col" className="py-1 pr-4 text-right">Value</th><th scope="col" className="py-1 pr-4">Status</th>
                    <th scope="col" className="py-1 pr-4">Target</th><th scope="col" className="py-1 pr-4">Trend</th><th scope="col" className="py-1">Definition</th>
                  </tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {g.items.map((i) => (
                      <tr key={i.code} id={i.code} className="align-top">
                        <th scope="row" className="py-2 pr-4 text-left font-medium">
                          <button type="button" className="text-left text-[#1A56DB] hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1A56DB]"
                            aria-expanded={open === i.code} onClick={() => setOpen(open === i.code ? null : i.code)}>{i.name}</button>
                          <span className="block font-mono text-[10px] font-normal text-slate-400">{i.code}{i.pointInTime ? ' · as of now' : ''}</span>
                        </th>
                        <td className="py-2 pr-4 text-right tabular-nums">{kpiValue(i)}</td>
                        <td className="py-2 pr-4"><StatusChip status={i.value === null ? 'PENDING' : STATUS_TONE[i.status]} /><span className="sr-only"> {i.status}</span></td>
                        <td className="py-2 pr-4 text-xs text-slate-600">{kpiTarget(i) ?? '–'}</td>
                        <td className="py-2 pr-4"><Sparkline name={i.name} points={(i.trend ?? []).map((t) => (t.value === null ? null : Number(t.value)))} /></td>
                        <td className="py-2 text-xs text-slate-600">
                          {i.formula}<br /><span className="text-slate-400">Source: {i.source}</span>
                          {i.value === null && typeof i.detail?.needs === 'string' && <><br /><span className="text-amber-700">Waiting for data: {i.detail.needs}</span></>}
                          {typeof i.detail?.error === 'string' && <><br /><span className="text-red-700">{i.detail.error}</span></>}
                          {i.templates.length > 0 && <><br /><span className="text-slate-400">Template: {i.templates.map(label).join(', ')}</span></>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {g.items.some((i) => i.code === open) && (
                <div className="mt-3 rounded-lg bg-slate-50 p-3 text-sm" role="region" aria-label={`History of ${open}`}>
                  {detail.isLoading ? <Loading /> : detail.data ? (
                    <>
                      <p className="font-medium">{detail.data.name}: numerator {detail.data.numerator ?? '–'}, denominator {detail.data.denominator ?? '–'}</p>
                      {detail.data.history.length ? (
                        <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-700">
                          {detail.data.history.map((h) => <li key={h.period}>{h.period}: <span className="tabular-nums">{kpiValue({ value: h.value, unit: detail.data!.unit })}</span> ({h.status.toLowerCase()})</li>)}
                        </ul>
                      ) : <p className="mt-1 text-xs text-slate-500">No month-end snapshot yet: the scheduler (or Save snapshot) creates them.</p>}
                    </>
                  ) : null}
                </div>
              )}
            </Card>
          ))}
        </>
      )}
    </div>
  );
}

export default function KpiExplorer() {
  return <Suspense fallback={<Loading />}><Explorer /></Suspense>;
}
