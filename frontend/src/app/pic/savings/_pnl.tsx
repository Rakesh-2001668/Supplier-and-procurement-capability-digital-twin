'use client';

import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Button, Card, DataTable, Empty, Field, Kpi, Loading, ProblemBox, Select } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { crore, inr } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Month = { period: string; realisedMinor: number; validatedMinor: number; pendingValidationMinor: number; negotiatedMinor: number; avoidanceMinor: number; cumulativeValidatedMinor: number } & Record<string, unknown>;
type Cat = { category: string; realisedMinor: number; validatedMinor: number; pendingValidationMinor: number; negotiatedMinor: number; avoidanceMinor: number;
  planBudgetMinor: number | null; planTargetMinor: number | null; attainmentPct: string | null } & Record<string, unknown>;
type Queue = { id: string; number: string; title: string; category: string; stage: string; realisedMinor: number; owner: string | null; canValidate: boolean } & Record<string, unknown>;
type Pnl = {
  fiscalYear: string; months: Month[]; categories: Cat[]; validationQueue: Queue[]; rule: string;
  totals: { realisedMinor: number; validatedMinor: number; pendingValidationMinor: number; negotiatedMinor: number; avoidanceMinor: number; budgetImpactMinor: number;
    planTargetMinor: number | null; attainmentPct: string | null };
};

function fiscalYears(): string[] {
  const now = new Date();
  const start = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  return [start + 1, start, start - 1].map((y) => `${y}-${String(y + 1).slice(-2)}`);
}

/** M11-C4: savings P&L and budget impact for a fiscal year, with the finance validation queue. */
export function PnlTab() {
  const [fy, setFy] = useState('');
  const { data, isLoading, error } = useApi<Pnl>(`/savings/pnl${fy ? `?fiscal_year=${fy}` : ''}`);
  const validate = useCommand((number: string) => api.post(`/savings/${encodeURIComponent(number)}/validate`), { success: 'Savings validated by finance' });
  const years = [...new Set([...(data ? [data.fiscalYear] : []), ...fiscalYears()])].sort().reverse();
  const chart = (data?.months ?? []).map((m) => ({ period: m.period, Validated: m.validatedMinor / 100, 'Awaiting validation': m.pendingValidationMinor / 100 }));
  const tick = (v: number) => (Math.abs(v) >= 1e7 ? `₹${(v / 1e7).toFixed(1)} Cr` : Math.abs(v) >= 1e5 ? `₹${(v / 1e5).toFixed(1)} L` : `₹${Math.round(v)}`);

  return (
    <div className="space-y-6">
      <div className="max-w-xs">
        <Field label="Fiscal year">{(id) => <Select id={id} value={fy || data?.fiscalYear || ''} onChange={(e) => setFy(e.target.value)} options={years.map((y) => ({ value: y, label: y }))} />}</Field>
      </div>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : !data ? null : (
        <>
          <p className="text-sm text-slate-600">{data.rule}</p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Kpi label="Budget impact" value={crore(data.totals.budgetImpactMinor)} hint="validated realised savings" tone="good" />
            <Kpi label="Awaiting validation" value={crore(data.totals.pendingValidationMinor)} hint="realised, not yet signed off" tone={data.totals.pendingValidationMinor ? 'warn' : 'default'} />
            <Kpi label="Plan target" value={data.totals.planTargetMinor === null ? '–' : crore(data.totals.planTargetMinor)} hint={data.totals.attainmentPct === null ? 'no approved category plan' : `${data.totals.attainmentPct}% attained`} />
            <Kpi label="Negotiated" value={crore(data.totals.negotiatedMinor)} hint="reported, not counted" />
            <Kpi label="Cost avoidance" value={crore(data.totals.avoidanceMinor)} hint="reported, not counted" />
          </div>

          <Card title={`Monthly P&L effect, FY ${data.fiscalYear}`}>
            <div style={{ height: 260 }} role="img" aria-label="Monthly validated and unvalidated realised savings">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chart} margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
                  <CartesianGrid vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="period" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} tickFormatter={tick} />
                  <Tooltip formatter={(v) => tick(Number(v))} />
                  <Legend />
                  <Bar dataKey="Validated" stackId="a" fill="#1A56DB" />
                  <Bar dataKey="Awaiting validation" stackId="a" fill="#F59E0B" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-3">
              <DataTable<Month> caption="Savings by month" rows={data.months} columns={[
                { key: 'period', header: 'Month' },
                { key: 'validatedMinor', header: 'Validated', align: 'right', render: (r) => inr(r.validatedMinor) },
                { key: 'pendingValidationMinor', header: 'Awaiting validation', align: 'right', render: (r) => inr(r.pendingValidationMinor) },
                { key: 'cumulativeValidatedMinor', header: 'Cumulative validated', align: 'right', render: (r) => inr(r.cumulativeValidatedMinor) },
                { key: 'negotiatedMinor', header: 'Negotiated (not counted)', align: 'right', render: (r) => inr(r.negotiatedMinor) },
                { key: 'avoidanceMinor', header: 'Avoidance (not counted)', align: 'right', render: (r) => inr(r.avoidanceMinor) },
              ]} />
            </div>
          </Card>

          <Card title="By category against the category plan">
            {data.categories.length === 0 ? <Empty title="No savings posted in this fiscal year" /> : (
              <DataTable<Cat> caption="Savings by category" rows={data.categories} columns={[
                { key: 'category', header: 'Category' },
                { key: 'validatedMinor', header: 'Validated', align: 'right', render: (r) => inr(r.validatedMinor) },
                { key: 'pendingValidationMinor', header: 'Awaiting validation', align: 'right', render: (r) => inr(r.pendingValidationMinor) },
                { key: 'planTargetMinor', header: 'Plan target', align: 'right', render: (r) => (r.planTargetMinor === null ? '–' : inr(r.planTargetMinor)) },
                { key: 'attainmentPct', header: 'Attained', align: 'right', render: (r) => (r.attainmentPct === null ? '–' : `${r.attainmentPct}%`) },
                { key: 'avoidanceMinor', header: 'Avoidance', align: 'right', render: (r) => inr(r.avoidanceMinor) },
              ]} />
            )}
          </Card>

          <Card title="Finance validation queue">
            {data.validationQueue.length === 0 ? <Empty title="Nothing waits for validation" /> : (
              <DataTable<Queue> caption="Initiatives with realised savings that finance has not validated" rows={data.validationQueue} columns={[
                { key: 'number', header: 'Initiative', render: (r) => <span className="font-mono font-medium">{r.number}</span> },
                { key: 'title', header: 'Title', className: 'min-w-[200px]' },
                { key: 'stage', header: 'Stage' },
                { key: 'owner', header: 'Owner', render: (r) => r.owner ?? '–' },
                { key: 'realisedMinor', header: 'Realised', align: 'right', render: (r) => inr(r.realisedMinor) },
                { key: 'id', header: '', render: (r) => (r.canValidate
                  ? <Button variant="primary" busy={validate.isPending} onClick={() => validate.mutate(r.number)} aria-label={`Validate ${r.number}`}>Validate</Button>
                  : <span className="text-xs text-slate-500">{r.stage === 'REALISING' ? 'Owner cannot validate (SOD-07)' : 'Not yet realising'}</span>) },
              ]} />
            )}
            <p className="mt-2 text-xs text-slate-500">Validation needs the finance controller role; the initiative owner can never validate their own savings.</p>
          </Card>
        </>
      )}
    </div>
  );
}
