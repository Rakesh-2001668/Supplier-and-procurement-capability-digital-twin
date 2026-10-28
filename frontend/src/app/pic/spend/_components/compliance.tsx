'use client';

import Link from 'next/link';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card, DataTable, Empty, Kpi, Loading } from '@/components/pic/ui';
import { crore, inr, label } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { pct, period, periodRange, rupeeTick, ShareBar, SpendProblem } from './shared';

type CategoryRow = { category: string; contractedMinor: number; nonContractedMinor: number; priceVarianceMinor: number; offContractLines: number; coveragePct: string };
type OffLine = { invoice: string; po: string | null; supplier: string | null; category: string; period: string; amountMinor: number; priceVarianceMinor: number; flags: string[] };
type Compliance = { periods: [string, string]; categories: CategoryRow[]; offContract: OffLine[]; leakageMinor: number };

const CONTRACTED = '#2a78d6';
const NON_CONTRACTED = '#eb6834';

function ComplianceTooltip({ active, payload }: { active?: boolean; payload?: { payload: CategoryRow }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
      <p className="font-semibold text-slate-900">{p.category} · {p.coveragePct}% covered</p>
      <p className="tabular-nums text-slate-700">Contracted {inr(p.contractedMinor)}</p>
      <p className="tabular-nums text-slate-700">Not contracted {inr(p.nonContractedMinor)}</p>
      {p.priceVarianceMinor > 0 && <p className="tabular-nums text-slate-700">Price variance {inr(p.priceVarianceMinor)}</p>}
    </div>
  );
}

/** SPD-05 contract compliance: contracted vs non-contracted spend, off-contract lines and price leakage. */
export function ComplianceTab() {
  const { data, isLoading, error } = useApi<Compliance>('/spend/compliance');
  if (isLoading) return <Loading />;
  if (error) return <SpendProblem error={error} />;
  if (!data?.categories.length) return <Empty title="No addressable spend in the last 12 months" />;

  const contracted = data.categories.reduce((s, c) => s + c.contractedMinor, 0);
  const non = data.categories.reduce((s, c) => s + c.nonContractedMinor, 0);
  const chart = data.categories.map((c) => ({ ...c, contracted: c.contractedMinor / 100, nonContracted: c.nonContractedMinor / 100 }));

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">Addressable spend, {periodRange(data.periods)}. Contracted means the invoice line was priced from a contract or catalogue.</p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Contracted" value={crore(contracted)} hint={inr(contracted)} tone="good" />
        <Kpi label="Not contracted" value={crore(non)} hint={inr(non)} tone={non ? 'warn' : 'default'} />
        <Kpi label="Contract coverage" value={pct(contracted + non ? ((contracted * 100) / (contracted + non)).toFixed(1) : '0')} />
        <Kpi label="Price leakage" value={inr(data.leakageMinor)} hint="invoiced above contract price on off-contract lines" tone={data.leakageMinor ? 'bad' : 'good'} />
      </div>

      <Card title="Coverage by category">
        <div style={{ height: Math.max(160, chart.length * 32 + 60) }} role="img" aria-label="Stacked bars of contracted and non-contracted spend per category; the table below lists the same values">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }} barCategoryGap={6}>
              <CartesianGrid horizontal={false} stroke="#e2e8f0" />
              <XAxis type="number" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} tickFormatter={rupeeTick} />
              <YAxis type="category" dataKey="category" width={130} tick={{ fontSize: 11, fill: '#334155' }} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ fill: '#f1f5f9' }} content={<ComplianceTooltip />} />
              <Legend verticalAlign="top" height={28} iconType="square" wrapperStyle={{ fontSize: 12, color: '#334155' }} />
              <Bar dataKey="contracted" name="Contracted" stackId="s" fill={CONTRACTED} stroke="#ffffff" strokeWidth={1} maxBarSize={20} />
              <Bar dataKey="nonContracted" name="Not contracted" stackId="s" fill={NON_CONTRACTED} stroke="#ffffff" strokeWidth={1} radius={[0, 4, 4, 0]} maxBarSize={20} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-4">
          <DataTable<CategoryRow> rows={data.categories} columns={[
            { key: 'category', header: 'Category', render: (r) => <span className="font-mono text-xs font-semibold">{r.category}</span> },
            { key: 'contractedMinor', header: 'Contracted', align: 'right', render: (r) => inr(r.contractedMinor) },
            { key: 'nonContractedMinor', header: 'Not contracted', align: 'right', render: (r) => inr(r.nonContractedMinor) },
            { key: 'coveragePct', header: 'Coverage', render: (r) => <ShareBar value={Number(r.coveragePct)} label={`${r.coveragePct}%`} /> },
            { key: 'offContractLines', header: 'Off-contract lines', align: 'right' },
            { key: 'priceVarianceMinor', header: 'Price variance', align: 'right', render: (r) => (r.priceVarianceMinor ? <span className="font-medium text-red-700">{inr(r.priceVarianceMinor)}</span> : '–') },
          ]} />
        </div>
      </Card>

      <Card title={`Off-contract lines (${data.offContract.length}${data.offContract.length === 100 ? ', largest 100' : ''})`}>
        <DataTable<OffLine & { id: string }> rows={data.offContract.map((o, i) => ({ ...o, id: `${o.invoice}-${i}` }))} empty="No off-contract or off-price lines" columns={[
          { key: 'invoice', header: 'Invoice', render: (r) => <span className="font-mono text-xs">{r.invoice}</span> },
          { key: 'po', header: 'PO', render: (r) => (r.po ? <span className="font-mono text-xs">{r.po}</span> : '–') },
          { key: 'supplier', header: 'Supplier', render: (r) => (r.supplier ? <Link href={`/pic/suppliers/${encodeURIComponent(r.supplier)}`} className="font-mono text-xs font-medium text-[#1A56DB] hover:underline">{r.supplier}</Link> : '–') },
          { key: 'category', header: 'Category', render: (r) => <span className="font-mono text-xs">{r.category}</span> },
          { key: 'period', header: 'Period', render: (r) => period(r.period) },
          { key: 'amountMinor', header: 'Amount', align: 'right', render: (r) => inr(r.amountMinor) },
          { key: 'priceVarianceMinor', header: 'Above contract', align: 'right', render: (r) => (r.priceVarianceMinor ? inr(r.priceVarianceMinor) : '–') },
          { key: 'flags', header: 'Flags', render: (r) => <span className="text-xs text-slate-600">{r.flags.map(label).join(', ')}</span> },
        ]} />
      </Card>
    </div>
  );
}
