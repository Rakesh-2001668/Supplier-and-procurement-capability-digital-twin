'use client';

import Link from 'next/link';
import { useCallback, useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Button, Card, DataTable, Empty, Field, Input, Kpi, Loading, Select } from '@/components/pic/ui';
import { SavedViews } from '@/components/pic/views';
import { api } from '@/lib/pic/api';
import { crore, inr, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { CubeState, CubeStatus, linesHref, linkClass, rupeeTick, SpendProblem } from './shared';

type CubeRow = Record<string, string | number | boolean | null> & {
  spendMinor: number; lines: number; invoices: number; pos: number; contractedMinor: number; maverickMinor: number; priceVarianceMinor: number;
  priceVarianceLastMinor: number; consumptionMinor: number; contractCoveragePct: string;
};
type Cube = {
  dimensions: string[]; currency: string; totalMinor: number; contractedPct: string; maverickPct: string; rows: CubeRow[]; truncated: boolean; freshness: CubeState; scope: Record<string, unknown> | null;
  totals: CubeRow; documentCurrencyTotals?: Record<string, number>;
  commitments?: { totals: { committedMinor: number; receivedNotInvoicedMinor: number } };
};
type Me = { scopes: string[] };

const DIMENSIONS = [
  ['category', 'Category (leaf)'], ['category_l1', 'Category L1'], ['category_l2', 'Category L2'], ['category_l3', 'Category L3'], ['category_l4', 'Category L4'],
  ['supplier', 'Supplier'], ['parent_supplier', 'Parent supplier'], ['plant', 'Plant'], ['company_code', 'Company code'], ['cost_object', 'Cost centre / WBS'],
  ['material_group', 'Material group'], ['buyer', 'Buyer'], ['period', 'Period'], ['fiscal_year', 'Fiscal year'], ['fiscal_quarter', 'Fiscal quarter'], ['year', 'Calendar year'], ['quarter', 'Calendar quarter'], ['currency', 'Currency'], ['source_system', 'ERP system'], ['contracted', 'Contracted'],
].map(([value, name]) => ({ value, label: name }));
const dimLabel = (d: string) => DIMENSIONS.find((x) => x.value === d)?.label ?? label(d);
const UNASSIGNED = '(not assigned)';

type Filters = {
  dims: string[]; periodFrom: string; periodTo: string; category: string; supplier: string; parent: string; plant: string; companyCode: string;
  costCentre: string; wbs: string; buyer: string; currency: string; sourceSystem: string; contracted: '' | 'true' | 'false'; commitments: boolean;
};
const INITIAL: Filters = { dims: ['category'], periodFrom: '', periodTo: '', category: '', supplier: '', parent: '', plant: '', companyCode: '', costCentre: '', wbs: '', buyer: '',
  currency: '', sourceSystem: '', contracted: '', commitments: true };

function queryOf(f: Filters): string {
  const q = new URLSearchParams({ dims: f.dims.join(','), limit: '500', commitments: String(f.commitments) });
  const map: [string, string][] = [['period_from', f.periodFrom], ['period_to', f.periodTo], ['category', f.category], ['supplier', f.supplier], ['parent', f.parent],
    ['plant', f.plant], ['buyer', f.buyer], ['company_code', f.companyCode], ['cost_centre', f.costCentre], ['wbs', f.wbs], ['currency', f.currency], ['source_system', f.sourceSystem],
    ['contracted', f.contracted]];
  for (const [k, v] of map) if (v) q.set(k, v);
  return q.toString();
}

/** The lines screen for one cube row: the row's dimension values plus the filters in force. */
function drillHref(row: CubeRow, dims: string[], f: Filters): string {
  const q: Record<string, string | undefined> = {
    period_from: f.periodFrom, period_to: f.periodTo, category: f.category, supplier: f.supplier, parent: f.parent, plant: f.plant, company_code: f.companyCode,
    buyer: f.buyer, currency: f.currency, contracted: f.contracted,
  };
  for (const d of dims) {
    const v = row[d];
    if (v === null || v === undefined || v === '') continue;
    const value = String(v);
    if (d.startsWith('category')) q.category = value;
    else if (d === 'supplier') q.supplier = value;
    else if (d === 'parent_supplier') q.parent = value;
    else if (d === 'plant' || d === 'company_code' || d === 'buyer' || d === 'currency') q[d] = value;
    else if (d === 'period') { q.period_from = value; q.period_to = value; }
    else if (d === 'contracted') q.contracted = String(v);
  }
  return linesHref(q);
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: { name: string; spendMinor: number; lines: number } }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
      <p className="font-semibold text-slate-900">{p.name}</p>
      <p className="tabular-nums text-slate-700">{inr(p.spendMinor)}</p>
      <p className="text-slate-500">{p.lines} invoice line{p.lines === 1 ? '' : 's'}</p>
    </div>
  );
}

/** SPD-04 spend cube: summaries by category L1-L4, supplier (parent / child), plant, company, cost centre / WBS, currency and ERP, with filters. */
export function CubeTab() {
  const [f, setF] = useState<Filters>(INITIAL);
  const set = <K extends keyof Filters>(key: K, value: Filters[K]) => setF((cur) => ({ ...cur, [key]: value }));
  const apply = useCallback((saved: Record<string, unknown>) => setF({ ...INITIAL, ...(saved as Partial<Filters>) }), []);
  const { data, isLoading, error } = useApi<Cube>(`/spend/analysis?${queryOf(f)}`);
  const me = useApi<Me>('/me');
  const plants = useApi<{ plants: { code: string; name: string }[] }>('/reference');
  const refresh = useCommand(() => api.post('/admin/spend/refresh', { full: false }), { success: 'Cube refreshed' });
  const canRefresh = !!me.data?.scopes.includes('admin:integration');

  function toggle(d: string) {
    setF((cur) => ({ ...cur, dims: cur.dims.includes(d) ? (cur.dims.length > 1 ? cur.dims.filter((x) => x !== d) : cur.dims) : [...cur.dims, d] }));
  }

  const first = data?.dimensions[0] ?? f.dims[0];
  const chartData = useMemo(() => {
    if (!data) return [];
    const totals = new Map<string, { name: string; spendMinor: number; lines: number }>();
    for (const r of data.rows) {
      const name = r[first] == null ? UNASSIGNED : String(r[first]);
      const cur = totals.get(name) ?? { name, spendMinor: 0, lines: 0 };
      cur.spendMinor += Number(r.spendMinor);
      cur.lines += Number(r.lines);
      totals.set(name, cur);
    }
    return [...totals.values()].sort((a, b) => b.spendMinor - a.spendMinor).slice(0, 20).map((x) => ({ ...x, rupees: x.spendMinor / 100 }));
  }, [data, first]);

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">
        Spend cube from posted invoice lines, served from precomputed summaries so it answers in well under a second at 50 million lines. Amounts are in the group currency
        (converted with the exchange rate stored on each line). Contracted is spend on a contract or catalogue price; consumption is the contract-covered part. Group by fiscal or calendar year and quarter, or by buyer, and follow “Lines” on a row to the posted lines behind it.
      </p>
      <Card title="Dimensions" actions={<span className="text-xs text-slate-500">The chart groups by the first dimension selected</span>}>
        <fieldset>
          <legend className="sr-only">Group spend by</legend>
          <div className="flex flex-wrap gap-2">
            {DIMENSIONS.map((d) => {
              const idx = f.dims.indexOf(d.value);
              const on = idx >= 0;
              return (
                <label key={d.value} className={`inline-flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-sm focus-within:ring-2 focus-within:ring-[#1A56DB] ${on ? 'border-[#1A56DB] bg-blue-50 text-[#1A56DB]' : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'}`}>
                  <input type="checkbox" className="accent-[#1A56DB]" checked={on} onChange={() => toggle(d.value)} />
                  {d.label}
                  {on && <span className="rounded bg-white px-1 font-mono text-[10px] text-slate-500 ring-1 ring-slate-200">{idx + 1}</span>}
                </label>
              );
            })}
          </div>
        </fieldset>
      </Card>

      <Card title="Filters" actions={<SavedViews screen="spend-analysis" filters={f} onApply={apply} />}>
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="From month">{(id) => <Input id={id} type="month" value={f.periodFrom} onChange={(e) => set('periodFrom', e.target.value)} />}</Field>
          <Field label="To month">{(id) => <Input id={id} type="month" value={f.periodTo} onChange={(e) => set('periodTo', e.target.value)} />}</Field>
          <Field label="Category (any level)" hint="Taxonomy code, e.g. DIRECT or ALU-DIECAST">{(id, d) => <Input id={id} aria-describedby={d} value={f.category} onChange={(e) => set('category', e.target.value.toUpperCase())} />}</Field>
          <Field label="Plant">{(id) => <Select id={id} value={f.plant} onChange={(e) => set('plant', e.target.value)}
            options={[{ value: '', label: 'All plants' }, ...(plants.data?.plants ?? []).map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))]} />}</Field>
          <Field label="Supplier code">{(id) => <Input id={id} value={f.supplier} onChange={(e) => set('supplier', e.target.value)} />}</Field>
          <Field label="Parent supplier code">{(id) => <Input id={id} value={f.parent} onChange={(e) => set('parent', e.target.value)} />}</Field>
          <Field label="Company code">{(id) => <Input id={id} value={f.companyCode} onChange={(e) => set('companyCode', e.target.value)} />}</Field>
          <Field label="Currency">{(id) => <Input id={id} value={f.currency} maxLength={3} onChange={(e) => set('currency', e.target.value.toUpperCase())} />}</Field>
          <Field label="Cost centre">{(id) => <Input id={id} value={f.costCentre} onChange={(e) => set('costCentre', e.target.value)} />}</Field>
          <Field label="WBS element">{(id) => <Input id={id} value={f.wbs} onChange={(e) => set('wbs', e.target.value)} />}</Field>
          <Field label="Buyer (e-mail)" hint="Purchasing buyer of the order">{(id, d) => <Input id={id} aria-describedby={d} value={f.buyer} onChange={(e) => set('buyer', e.target.value)} />}</Field>
          <Field label="ERP system">{(id) => <Input id={id} value={f.sourceSystem} onChange={(e) => set('sourceSystem', e.target.value)} />}</Field>
          <Field label="Contracted">{(id) => <Select id={id} value={f.contracted} onChange={(e) => set('contracted', e.target.value as Filters['contracted'])}
            options={[{ value: '', label: 'Both' }, { value: 'true', label: 'Contracted only' }, { value: 'false', label: 'Not contracted only' }]} />}</Field>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-[#1A56DB]" checked={f.commitments} onChange={(e) => set('commitments', e.target.checked)} /> Include open PO commitments</label>
          <Button variant="ghost" onClick={() => setF(INITIAL)}>Clear filters</Button>
        </div>
      </Card>

      {isLoading ? <Loading /> : error ? <SpendProblem error={error} /> : !data || data.rows.length === 0 ? (
        <Empty title="No spend for these filters" hint="Spend appears when invoices are posted to the ERP." />
      ) : (
        <>
          <CubeStatus state={data.freshness} scope={data.scope} />
          {canRefresh && <div><Button busy={refresh.isPending} onClick={() => refresh.mutate()}>Refresh now</Button></div>}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
            <Kpi label="Posted spend" value={crore(data.totalMinor)} hint={`${inr(data.totalMinor)} · ${data.currency}`} />
            <Kpi label="Contracted" value={`${data.contractedPct}%`} hint="contract or catalogue price" tone="good" />
            <Kpi label="Maverick" value={`${data.maverickPct}%`} hint="off-contract spend" tone={Number(data.maverickPct) > 0 ? 'warn' : 'default'} />
            <Kpi label="Price variance" value={crore(data.totals.priceVarianceMinor)} hint={`vs last price ${crore(data.totals.priceVarianceLastMinor)}`} tone={data.totals.priceVarianceMinor ? 'warn' : 'default'} />
            <Kpi label="Invoices / POs" value={`${data.totals.invoices} / ${data.totals.pos}`} hint={`${data.totals.lines} lines`} />
            {data.commitments && <Kpi label="Open PO commitments" value={crore(data.commitments.totals.committedMinor)} hint={`received not invoiced ${crore(data.commitments.totals.receivedNotInvoicedMinor)}`} />}
          </div>
          {data.documentCurrencyTotals && (
            <p className="text-xs text-slate-600">Document currencies: {Object.entries(data.documentCurrencyTotals).map(([c, a]) => `${c} ${(a / 100).toLocaleString('en-IN')}`).join(' · ')}</p>
          )}

          <Card title={`Spend by ${dimLabel(first).toLowerCase()}`} actions={chartData.length === 20 ? <span className="text-xs text-slate-500">top 20</span> : undefined}>
            <div style={{ height: Math.max(120, chartData.length * 36 + 40) }} role="img" aria-label={`Bar chart of spend by ${dimLabel(first).toLowerCase()}`}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }} barCategoryGap={8}>
                  <CartesianGrid horizontal={false} stroke="#e2e8f0" />
                  <XAxis type="number" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} tickFormatter={rupeeTick} />
                  <YAxis type="category" dataKey="name" width={140} tick={{ fontSize: 12, fill: '#334155' }} axisLine={false} tickLine={false} />
                  <Tooltip cursor={{ fill: '#f1f5f9' }} content={<ChartTooltip />} />
                  <Bar dataKey="rupees" name="Spend" fill="#1A56DB" radius={[0, 4, 4, 0]} maxBarSize={22} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card title="Spend cube" actions={data.truncated ? <span className="text-xs text-amber-700">showing the largest 500 cells; narrow the filters</span> : undefined}>
            <DataTable<CubeRow>
              caption={`Spend grouped by ${data.dimensions.map(dimLabel).join(', ')}`}
              rows={data.rows}
              columns={[
                ...data.dimensions.map((d) => ({ key: d, header: dimLabel(d), render: (r: CubeRow) => (r[d] == null || r[d] === '' ? <span className="text-slate-500">{UNASSIGNED}</span> : String(r[d])) })),
                { key: 'spendMinor', header: 'Spend', align: 'right' as const, render: (r: CubeRow) => inr(r.spendMinor) },
                { key: 'invoices', header: 'Invoices', align: 'right' as const },
                { key: 'pos', header: 'POs', align: 'right' as const },
                { key: 'consumptionMinor', header: 'Contract consumption', align: 'right' as const, render: (r: CubeRow) => inr(r.consumptionMinor) },
                { key: 'contractCoveragePct', header: 'Coverage', align: 'right' as const, render: (r: CubeRow) => `${r.contractCoveragePct}%` },
                { key: 'priceVarianceMinor', header: 'Price variance', align: 'right' as const, render: (r: CubeRow) => inr(r.priceVarianceMinor) },
                { key: 'priceVarianceLastMinor', header: 'vs last price', align: 'right' as const, render: (r: CubeRow) => inr(r.priceVarianceLastMinor) },
                { key: 'drill', header: '', render: (r: CubeRow) => <Link href={drillHref(r, data.dimensions, f)} prefetch={false} className={linkClass} aria-label="Drill to the spend lines of this row">Lines →</Link> },
              ]}
            />
          </Card>
        </>
      )}
    </div>
  );
}
