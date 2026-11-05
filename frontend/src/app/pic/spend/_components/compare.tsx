'use client';

import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card, DataTable, Empty, Field, Input, Kpi, Loading, Select } from '@/components/pic/ui';
import { crore, inr, label } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { ChangePct, ChartBox, fiscalYearsBack, pct, period, periodRange, rupeeTick, SpendProblem } from './shared';

type Summary = {
  fiscalYear: string; periods: [string, string]; currency: string; spendMinor: number; invoicedMinor: number; debitNoteMinor: number; creditNoteMinor: number;
  committedMinor: number; receivedNotInvoicedMinor: number; savingsRealisedMinor: number; savingsNegotiatedMinor: number; priceVarianceMinor: number;
  invoices: number; pos: number; lines: number; addressablePct: string; contractCoveragePct: string; maverickPct: string; underManagementPct: string;
  suppliers: number; tailSuppliers: number; tailSpendPct: string; maxHhi: number; categories: number; fxMissingLines: number;
  byPeriod: { period: string; spendMinor: number; invoicedMinor: number; creditNoteMinor: number }[];
};
type CompRow = Record<string, string | number | null> & {
  ytdMinor: number; priorYtdMinor: number; ytdChangePct: string | null; trailing12Minor: number; prior12Minor: number; yoyChangePct: string | null;
  lastQuarterMinor: number; prevQuarterMinor: number; qoqChangePct: string | null; runRateAnnualMinor: number; sharePct: string;
};
type Comparison = {
  anchor: string; fiscalYearStartMonth: number; windows: Record<string, [string, string]>; dimensions: string[]; totals: CompRow; rows: CompRow[]; truncated: boolean;
  currency: string; definitions: Record<string, string>;
};

const DIMS = [
  ['category', 'Category'], ['category_l1', 'Category L1'], ['category_l2', 'Category L2'], ['supplier', 'Supplier'], ['parent_supplier', 'Parent supplier'],
  ['plant', 'Plant'], ['company_code', 'Company code'], ['buyer', 'Buyer'], ['source_system', 'ERP system'],
].map(([value, name]) => ({ value, label: name }));

function PeriodTooltip({ active, payload }: { active?: boolean; payload?: { payload: { name: string; spend: number; credit: number } }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
      <p className="font-semibold text-slate-900">{p.name}</p>
      <p className="tabular-nums text-slate-700">Spend {inr(p.spend * 100)}</p>
      <p className="tabular-nums text-slate-500">Credit notes {inr(p.credit * 100)}</p>
    </div>
  );
}

/** The measure set of one fiscal year and the period comparisons: YTD vs prior YTD, YoY, QoQ, run-rate and share of spend. */
export function CompareTab() {
  const [fy, setFy] = useState('');
  const [plant, setPlant] = useState('');
  const [dim, setDim] = useState('category');
  const [anchor, setAnchor] = useState('');
  const plants = useApi<{ plants: { code: string; name: string }[] }>('/reference');
  const summaryQs = new URLSearchParams();
  if (fy) summaryQs.set('fiscal_year', fy);
  if (plant) summaryQs.set('plant', plant);
  const summary = useApi<Summary>(`/spend/summary?${summaryQs.toString()}`);
  const compQs = new URLSearchParams({ dims: dim, limit: '200' });
  if (anchor) compQs.set('anchor', anchor);
  if (plant) compQs.set('plant', plant);
  const comparison = useApi<Comparison>(`/spend/comparison?${compQs.toString()}`);
  const s = summary.data;
  const years = fiscalYearsBack(s?.fiscalYear);
  const chart = (s?.byPeriod ?? []).map((p) => ({ name: period(p.period), spend: p.spendMinor / 100, credit: Math.abs(p.creditNoteMinor) / 100 }));
  const c = comparison.data;

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">
        The measure set of one fiscal year, and how spend moves against the year before. Spend is posted invoices plus debit notes less credit notes, net of tax, in the group currency.
      </p>
      <Card title="Scope">
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Fiscal year" hint="Default: the year of the latest complete month">{(id, d) => (
            <Select id={id} aria-describedby={d} value={fy} onChange={(e) => setFy(e.target.value)}
              options={[{ value: '', label: s ? `Current (${s.fiscalYear})` : 'Current' }, ...years.map((y) => ({ value: y, label: y }))]} />
          )}</Field>
          <Field label="Plant">{(id) => (
            <Select id={id} value={plant} onChange={(e) => setPlant(e.target.value)}
              options={[{ value: '', label: 'All plants' }, ...(plants.data?.plants ?? []).map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))]} />
          )}</Field>
        </div>
      </Card>

      {summary.isLoading ? <Loading /> : summary.error ? <SpendProblem error={summary.error} /> : s && (
        <>
          <h2 className="text-sm font-semibold text-slate-900">Fiscal year {s.fiscalYear} · {periodRange(s.periods)} · {s.currency}</h2>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
            <Kpi label="Spend" value={crore(s.spendMinor)} hint={inr(s.spendMinor)} />
            <Kpi label="Invoiced" value={crore(s.invoicedMinor)} hint={`${s.invoices} invoices · ${s.lines} lines`} />
            <Kpi label="Debit notes" value={crore(s.debitNoteMinor)} />
            <Kpi label="Credit notes" value={crore(s.creditNoteMinor)} hint="reduce spend" />
            <Kpi label="Committed" value={crore(s.committedMinor)} hint={`open POs · ${s.pos} POs in year`} />
            <Kpi label="Received not invoiced" value={crore(s.receivedNotInvoicedMinor)} />
            <Kpi label="Savings realised" value={crore(s.savingsRealisedMinor)} hint={`negotiated ${crore(s.savingsNegotiatedMinor)}`} tone="good" />
            <Kpi label="Price variance" value={crore(s.priceVarianceMinor)} tone={s.priceVarianceMinor ? 'warn' : 'default'} hint="paid above contract / standard" />
            <Kpi label="Addressable" value={pct(s.addressablePct)} />
            <Kpi label="Contract coverage" value={pct(s.contractCoveragePct)} tone="good" />
            <Kpi label="Maverick" value={pct(s.maverickPct)} tone={Number(s.maverickPct) > 5 ? 'warn' : 'default'} />
            <Kpi label="Under management" value={pct(s.underManagementPct)} tone="good" />
            <Kpi label="Suppliers" value={s.suppliers} hint={`${s.tailSuppliers} in the tail (${pct(s.tailSpendPct)} of spend)`} />
            <Kpi label="Categories" value={s.categories} hint={`highest HHI ${s.maxHhi.toLocaleString('en-IN')}`} />
            <Kpi label="FX rate missing" value={s.fxMissingLines} tone={s.fxMissingLines ? 'bad' : 'default'} hint="lines left out of totals" />
          </div>
          <Card title="Spend by month">
            {chart.length ? (
              <ChartBox height={260} label={`Bar chart of monthly spend in fiscal year ${s.fiscalYear}`}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chart} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
                    <CartesianGrid vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={{ stroke: '#cbd5e1' }} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} width={72} tickFormatter={rupeeTick} />
                    <Tooltip cursor={{ fill: '#f1f5f9' }} content={<PeriodTooltip />} />
                    <Bar dataKey="spend" name="Spend" fill="#1A56DB" radius={[4, 4, 0, 0]} maxBarSize={36} />
                  </BarChart>
                </ResponsiveContainer>
              </ChartBox>
            ) : <Empty title="No spend in this fiscal year" />}
          </Card>
        </>
      )}

      <Card title="Period comparisons" actions={<span className="text-xs text-slate-500">{c ? `Anchor ${period(c.anchor)} · fiscal year starts in month ${c.fiscalYearStartMonth}` : ''}</span>}>
        <div className="mb-4 grid gap-3 md:grid-cols-4">
          <Field label="Compare by">{(id) => <Select id={id} value={dim} onChange={(e) => setDim(e.target.value)} options={DIMS} />}</Field>
          <Field label="Anchor month" hint="Blank: the latest complete month">{(id, d) => <Input id={id} aria-describedby={d} type="month" value={anchor} onChange={(e) => setAnchor(e.target.value)} />}</Field>
        </div>
        {comparison.isLoading ? <Loading /> : comparison.error ? <SpendProblem error={comparison.error} /> : !c || !c.rows.length ? (
          <Empty title="Nothing to compare" hint="The filter has no spend in the comparison windows." />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Kpi label="YTD" value={crore(c.totals.ytdMinor)} hint={<>vs {crore(c.totals.priorYtdMinor)} · <ChangePct value={c.totals.ytdChangePct} /></>} />
              <Kpi label="Year on year" value={crore(c.totals.trailing12Minor)} hint={<>vs {crore(c.totals.prior12Minor)} · <ChangePct value={c.totals.yoyChangePct} /></>} />
              <Kpi label="Quarter on quarter" value={crore(c.totals.lastQuarterMinor)} hint={<>vs {crore(c.totals.prevQuarterMinor)} · <ChangePct value={c.totals.qoqChangePct} /></>} />
              <Kpi label="Run-rate (annual)" value={crore(c.totals.runRateAnnualMinor)} hint="last 3 months x 4" />
            </div>
            <p className="text-xs text-slate-600">
              Windows: {Object.entries(c.windows).map(([k, w]) => `${label(k.replace(/([A-Z])/g, '_$1'))} ${period(w[0])} – ${period(w[1])}`).join(' · ')}
            </p>
            <DataTable<CompRow & { id: string }> caption={`Period comparison by ${dim}`}
              rows={c.rows.map((r, i) => ({ ...r, id: `${i}-${String(r[c.dimensions[0]] ?? '')}` }))}
              columns={[
                ...c.dimensions.map((d) => ({ key: d, header: DIMS.find((x) => x.value === d)?.label ?? label(d), render: (r: CompRow) => (r[d] == null || r[d] === '' ? <span className="text-slate-500">(not assigned)</span> : String(r[d])) })),
                { key: 'ytdMinor', header: 'YTD', align: 'right' as const, render: (r: CompRow) => inr(r.ytdMinor) },
                { key: 'priorYtdMinor', header: 'Prior YTD', align: 'right' as const, render: (r: CompRow) => inr(r.priorYtdMinor) },
                { key: 'ytdChangePct', header: 'YTD change', align: 'right' as const, render: (r: CompRow) => <ChangePct value={r.ytdChangePct} /> },
                { key: 'trailing12Minor', header: 'Last 12 months', align: 'right' as const, render: (r: CompRow) => inr(r.trailing12Minor) },
                { key: 'yoyChangePct', header: 'YoY', align: 'right' as const, render: (r: CompRow) => <ChangePct value={r.yoyChangePct} /> },
                { key: 'lastQuarterMinor', header: 'Last quarter', align: 'right' as const, render: (r: CompRow) => inr(r.lastQuarterMinor) },
                { key: 'qoqChangePct', header: 'QoQ', align: 'right' as const, render: (r: CompRow) => <ChangePct value={r.qoqChangePct} /> },
                { key: 'runRateAnnualMinor', header: 'Run-rate', align: 'right' as const, render: (r: CompRow) => inr(r.runRateAnnualMinor) },
                { key: 'sharePct', header: 'Share', align: 'right' as const, render: (r: CompRow) => pct(r.sharePct) },
              ]} />
            {c.truncated && <p className="text-xs text-amber-700">Showing the first 200 rows by last-12-month spend.</p>}
            <dl className="grid gap-1 text-xs text-slate-600 md:grid-cols-2">
              {Object.entries(c.definitions).map(([k, v]) => <div key={k}><dt className="inline font-semibold">{k.toUpperCase()}: </dt><dd className="inline">{v}</dd></div>)}
            </dl>
          </div>
        )}
      </Card>
    </div>
  );
}
