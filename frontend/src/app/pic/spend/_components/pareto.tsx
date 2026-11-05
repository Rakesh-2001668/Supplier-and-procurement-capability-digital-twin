'use client';

import { useState } from 'react';
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card, DataTable, Empty, Field, Input, Kpi, Loading, Select } from '@/components/pic/ui';
import { crore, inr, label } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { ChartBox, LevelChip, pct, period, rupeeTick, ShareBar, SpendProblem } from './shared';

type ParetoRow = Record<string, string | number | null> & { rank: number; name: string | null; spendMinor: number; sharePct: string; cumulativePct: string; class: 'A' | 'B' | 'C' };
type Pareto = {
  by: string; totalMinor: number; count: number; classes: Record<'A' | 'B' | 'C', { count: number; spendMinor: number; spendPct: string }>;
  tailCount: number; tailSpendMinor: number; tailSpendPct: string; tailCountPct: string; netNegative: Record<string, string | number>[]; rows: ParetoRow[];
  truncated: boolean; currency: string; thresholds: { A: number; B: number };
};
type Structure = {
  totalMinor: number; currency: string;
  rows: { category: string; spendMinor: number; sharePct: string; suppliers: number; supplierRecords: number; hhi: number; level: string; topSupplier: string; topSupplierName: string; topSharePct: string }[];
};
type Potential = {
  window: [string, string]; currency: string; byLever: Record<string, number>; totalMinor: number; realisedLedgerMinor: number; note: string;
  byCategory: { category: string; spendMinor: number; totalMinor: number; consolidationMinor: number; contract_coverageMinor: number; price_recoveryMinor: number }[];
  assumptions: { consolidationSavingPct: string; contractSavingPct: string; priceRecovery: string };
};

const BY = [{ value: 'supplier', label: 'Supplier' }, { value: 'parent_supplier', label: 'Parent supplier' }, { value: 'category', label: 'Category' }];
const CLASS_COLOR = { A: '#1A56DB', B: '#eb6834', C: '#94a3b8' } as const;
const LEVER_TEXT: Record<string, string> = {
  CONSOLIDATION: 'Consolidate the tail onto fewer suppliers (tail spend x aggregation saving %)',
  CONTRACT_COVERAGE: 'Move off-contract spend onto contracts (off-contract spend x contract saving %)',
  PRICE_RECOVERY: 'Recover the price paid above contract or standard price',
};

/** Pareto / ABC ranking, the long tail, category structure (supplier counts and HHI) and the indicative savings potential by lever. */
export function ParetoTab() {
  const [by, setBy] = useState('supplier');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [plant, setPlant] = useState('');
  const [category, setCategory] = useState('');
  const plants = useApi<{ plants: { code: string; name: string }[] }>('/reference');
  const qs = new URLSearchParams({ by, limit: '500' });
  const common = new URLSearchParams();
  if (from) common.set('period_from', from);
  if (to) common.set('period_to', to);
  if (plant) common.set('plant', plant);
  const withCat = new URLSearchParams(common);
  if (category) withCat.set('category', category);
  for (const [k, v] of withCat) qs.set(k, v);
  const pareto = useApi<Pareto>(`/spend/pareto?${qs.toString()}`);
  const structure = useApi<Structure>(`/spend/category-structure?${common.toString()}`);
  const potentialQs = new URLSearchParams();
  if (plant) potentialQs.set('plant', plant);
  if (category) potentialQs.set('category', category);
  const potential = useApi<Potential>(`/spend/savings-potential?${potentialQs.toString()}`);
  const p = pareto.data;
  const keyOf = (r: ParetoRow) => String(r[by] ?? '');
  const chart = (p?.rows ?? []).slice(0, 30).map((r) => ({ name: keyOf(r), full: r.name ?? keyOf(r), rupees: r.spendMinor / 100, cumulative: Number(r.cumulativePct), klass: r.class }));

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">
        Where the spend concentrates. Class A is everything that starts below {p?.thresholds.A ?? 80}% cumulative spend, B up to {p?.thresholds.B ?? 95}%, C the long tail.
        Figures are shares of addressable spend; a supplier whose credits exceed its invoices is listed apart.
      </p>
      <Card title="Filters">
        <div className="grid gap-3 md:grid-cols-5">
          <Field label="Rank by">{(id) => <Select id={id} value={by} onChange={(e) => setBy(e.target.value)} options={BY} />}</Field>
          <Field label="From month">{(id) => <Input id={id} type="month" value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
          <Field label="To month">{(id) => <Input id={id} type="month" value={to} onChange={(e) => setTo(e.target.value)} />}</Field>
          <Field label="Plant">{(id) => (
            <Select id={id} value={plant} onChange={(e) => setPlant(e.target.value)}
              options={[{ value: '', label: 'All plants' }, ...(plants.data?.plants ?? []).map((x) => ({ value: x.code, label: `${x.code} · ${x.name}` }))]} />
          )}</Field>
          <Field label="Category" hint="Taxonomy code, any level">{(id, d) => <Input id={id} aria-describedby={d} value={category} onChange={(e) => setCategory(e.target.value.toUpperCase())} />}</Field>
        </div>
      </Card>

      {pareto.isLoading ? <Loading /> : pareto.error ? <SpendProblem error={pareto.error} /> : !p || !p.rows.length ? (
        <Empty title="No spend for these filters" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
            <Kpi label="Addressable spend" value={crore(p.totalMinor)} hint={`${p.count} ${label(by).toLowerCase()}${p.count === 1 ? '' : 's'}`} />
            {(['A', 'B', 'C'] as const).map((k) => (
              <Kpi key={k} label={`Class ${k}`} value={`${p.classes[k].count}`} hint={`${pct(p.classes[k].spendPct)} of spend · ${crore(p.classes[k].spendMinor)}`} tone={k === 'C' ? 'warn' : 'default'} />
            ))}
            <Kpi label="Long tail" value={pct(p.tailSpendPct)} hint={`${p.tailCount} (${pct(p.tailCountPct)}) of the ${label(by).toLowerCase()}s`} tone="warn" />
            <Kpi label="Net negative" value={p.netNegative.length} hint="credits above invoices" />
          </div>

          <Card title={`Pareto of ${label(by).toLowerCase()} spend`} actions={<span className="text-xs text-slate-500">{p.rows.length > 30 ? 'top 30 of ' + p.rows.length : `${p.rows.length} shown`}</span>}>
            <ChartBox height={340} label={`Pareto chart: spend per ${label(by).toLowerCase()} as bars and cumulative share as a line; the table below lists the same values`}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chart} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
                  <CartesianGrid vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#64748b' }} interval={0} angle={-35} textAnchor="end" height={64} axisLine={{ stroke: '#cbd5e1' }} tickLine={false} />
                  <YAxis yAxisId="l" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} width={72} tickFormatter={rupeeTick} />
                  <YAxis yAxisId="r" orientation="right" domain={[0, 100]} tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} width={40} tickFormatter={(v) => `${v}%`} />
                  <Tooltip formatter={(v, n) => (n === 'Cumulative %' ? `${v}%` : inr(Number(v) * 100))} />
                  <Legend verticalAlign="top" height={28} wrapperStyle={{ fontSize: 12 }} />
                  <Bar yAxisId="l" dataKey="rupees" name="Spend" fill="#1A56DB" radius={[4, 4, 0, 0]} maxBarSize={28} />
                  <Line yAxisId="r" dataKey="cumulative" name="Cumulative %" stroke="#eb6834" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </ChartBox>
            <div className="mt-4">
              <DataTable<ParetoRow & { id: string }> caption={`Ranking by ${by}`} rows={p.rows.map((r) => ({ ...r, id: `${r.rank}` }))} columns={[
                { key: 'rank', header: '#', align: 'right' as const },
                { key: by, header: label(by), render: (r: ParetoRow) => <span><span className="font-mono text-xs font-semibold">{keyOf(r)}</span>{r.name && r.name !== keyOf(r) && <span className="block text-xs text-slate-500">{r.name}</span>}</span> },
                { key: 'spendMinor', header: 'Spend', align: 'right' as const, render: (r: ParetoRow) => inr(r.spendMinor) },
                { key: 'sharePct', header: 'Share', render: (r: ParetoRow) => <ShareBar value={Number(r.sharePct)} max={Math.max(Number(p.rows[0].sharePct), 1)} label={`${r.sharePct}%`} /> },
                { key: 'cumulativePct', header: 'Cumulative', align: 'right' as const, render: (r: ParetoRow) => pct(r.cumulativePct) },
                { key: 'class', header: 'Class', render: (r: ParetoRow) => (
                  <span className="inline-flex items-center gap-1.5 text-sm font-semibold"><span className="h-2.5 w-2.5 rounded-full" style={{ background: CLASS_COLOR[r.class] }} aria-hidden />{r.class}{r.class === 'C' && <span className="text-xs font-normal text-slate-500">tail</span>}</span>
                ) },
              ]} />
              {p.truncated && <p className="mt-2 text-xs text-amber-700">Showing the first 500 ranks.</p>}
              {p.netNegative.length > 0 && (
                <p className="mt-2 text-xs text-slate-600">Net negative (credits above invoices): {p.netNegative.map((n) => `${String(n[by])} ${inr(Number(n.spendMinor))}`).join(' · ')}</p>
              )}
            </div>
          </Card>
        </>
      )}

      <Card title="Category structure" actions={<span className="text-xs text-slate-500">HHI on parent suppliers</span>}>
        {structure.isLoading ? <Loading /> : structure.error ? <SpendProblem error={structure.error} /> : (
          <DataTable<NonNullable<Structure['rows']>[number] & { id: string }> caption="Category structure" empty="No categories with spend" rows={(structure.data?.rows ?? []).map((r) => ({ ...r, id: r.category }))} columns={[
            { key: 'category', header: 'Category', render: (r) => <span className="font-mono text-xs font-semibold">{r.category}</span> },
            { key: 'spendMinor', header: 'Spend', align: 'right', render: (r) => crore(r.spendMinor) },
            { key: 'sharePct', header: 'Share', align: 'right', render: (r) => pct(r.sharePct) },
            { key: 'suppliers', header: 'Suppliers', align: 'right', render: (r) => <span>{r.suppliers}{r.supplierRecords !== r.suppliers && <span className="text-xs text-slate-500"> ({r.supplierRecords} records)</span>}</span> },
            { key: 'hhi', header: 'HHI', align: 'right', render: (r) => <span>{r.hhi.toLocaleString('en-IN')} <LevelChip level={r.level} /></span> },
            { key: 'topSupplier', header: 'Top supplier', render: (r) => <span><span className="font-mono text-xs">{r.topSupplier}</span><span className="block text-xs text-slate-500">{r.topSupplierName} · {pct(r.topSharePct)}</span></span> },
          ]} />
        )}
      </Card>

      <Card title="Savings potential by lever" actions={<span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-800 ring-1 ring-inset ring-amber-200">Indicative only</span>}>
        {potential.isLoading ? <Loading /> : potential.error ? <SpendProblem error={potential.error} /> : potential.data && (
          <div className="space-y-4">
            <p className="text-sm text-slate-700" role="note">{potential.data.note} Window {period(potential.data.window[0])} – {period(potential.data.window[1])}.</p>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Kpi label="Total potential" value={crore(potential.data.totalMinor)} hint="not a forecast, not realised" />
              {Object.entries(potential.data.byLever).map(([k, v]) => <Kpi key={k} label={label(k)} value={crore(v)} hint={LEVER_TEXT[k]} />)}
              <Kpi label="Realised (ledger)" value={crore(potential.data.realisedLedgerMinor)} hint="validated savings ledger" tone="good" />
            </div>
            <DataTable<Potential['byCategory'][number] & { id: string }> caption="Savings potential by category" empty="No category has potential" rows={potential.data.byCategory.map((r) => ({ ...r, id: r.category }))} columns={[
              { key: 'category', header: 'Category', render: (r) => <span className="font-mono text-xs font-semibold">{r.category}</span> },
              { key: 'spendMinor', header: 'Spend (12 months)', align: 'right', render: (r) => crore(r.spendMinor) },
              { key: 'consolidationMinor', header: 'Consolidation', align: 'right', render: (r) => inr(r.consolidationMinor) },
              { key: 'contract_coverageMinor', header: 'Contract coverage', align: 'right', render: (r) => inr(r.contract_coverageMinor) },
              { key: 'price_recoveryMinor', header: 'Price recovery', align: 'right', render: (r) => inr(r.price_recoveryMinor) },
              { key: 'totalMinor', header: 'Total', align: 'right', render: (r) => <span className="font-semibold">{inr(r.totalMinor)}</span> },
            ]} />
            <p className="text-xs text-slate-600">
              Assumptions: consolidation saving {potential.data.assumptions.consolidationSavingPct}% of tail spend, contract saving {potential.data.assumptions.contractSavingPct}% of off-contract spend; price recovery is {potential.data.assumptions.priceRecovery}.
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}
