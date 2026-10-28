'use client';

import { useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card, DataTable, Empty, Kpi, Loading } from '@/components/pic/ui';
import { crore, inr, label } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { rupeeTick, SpendProblem } from './shared';

type CubeRow = { spendMinor: number; lines: number; contractCoveragePct: string | null } & Record<string, string | number | null>;
type Cube = { dimensions: string[]; totalMinor: number; contractedPct: string | null; maverickPct: string | null; rows: CubeRow[] };

const DIMENSIONS = [
  { value: 'category', label: 'Category' },
  { value: 'supplier', label: 'Supplier' },
  { value: 'plant', label: 'Plant' },
  { value: 'period', label: 'Period' },
  { value: 'material_group', label: 'Material group' },
  { value: 'cost_object', label: 'Cost object' },
];
const dimLabel = (d: string) => DIMENSIONS.find((x) => x.value === d)?.label ?? label(d);
const UNASSIGNED = '(not assigned)';

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

/** SPD-04 spend cube: posted invoice lines grouped by up to six dimensions. */
export function CubeTab() {
  const [dims, setDims] = useState<string[]>(['category']);
  const { data, isLoading, error } = useApi<Cube>(`/spend/cube?dims=${dims.join(',')}`);

  function toggle(d: string) {
    setDims((cur) => (cur.includes(d) ? (cur.length > 1 ? cur.filter((x) => x !== d) : cur) : [...cur, d]));
  }

  const first = data?.dimensions[0] ?? dims[0];
  // Chart aggregates by the first dimension, largest first.
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
    return [...totals.values()].sort((a, b) => b.spendMinor - a.spendMinor).slice(0, 20)
      .map((x) => ({ ...x, rupees: x.spendMinor / 100 }));
  }, [data, first]);

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">Spend cube from posted invoice lines (all periods). Contracted share is spend covered by a contract or catalogue price; maverick is spend outside them.</p>
      <Card title="Dimensions" actions={<span className="text-xs text-slate-500">The chart groups by the first dimension selected</span>}>
        <fieldset>
          <legend className="sr-only">Group spend by</legend>
          <div className="flex flex-wrap gap-2">
            {DIMENSIONS.map((d) => {
              const idx = dims.indexOf(d.value);
              const on = idx >= 0;
              return (
                <label key={d.value} className={`inline-flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-sm ${on ? 'border-[#1A56DB] bg-blue-50 text-[#1A56DB]' : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'}`}>
                  <input type="checkbox" className="accent-[#1A56DB]" checked={on} onChange={() => toggle(d.value)} />
                  {d.label}
                  {on && <span className="rounded bg-white px-1 font-mono text-[10px] text-slate-500 ring-1 ring-slate-200">{idx + 1}</span>}
                </label>
              );
            })}
          </div>
        </fieldset>
      </Card>

      {isLoading ? <Loading /> : error ? <SpendProblem error={error} /> : !data || data.rows.length === 0 || Number(data.totalMinor) === 0 ? (
        <Empty title="No spend yet" hint="Spend appears when invoices are posted to the ERP." />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Posted spend" value={inr(data.totalMinor)} hint={crore(data.totalMinor)} />
            <Kpi label="Contracted" value={data.contractedPct === null ? '–' : `${data.contractedPct}%`} hint="contract or catalogue price" tone="good" />
            <Kpi label="Maverick" value={data.maverickPct === null ? '–' : `${data.maverickPct}%`} hint="off-contract spend"
              tone={Number(data.maverickPct) > 0 ? 'warn' : 'default'} />
            <Kpi label="Cells" value={data.rows.length} hint={data.dimensions.map(dimLabel).join(' × ')} />
          </div>

          <Card title={`Spend by ${dimLabel(first).toLowerCase()}`} actions={chartData.length === 20 ? <span className="text-xs text-slate-500">top 20</span> : undefined}>
            <div style={{ height: Math.max(120, chartData.length * 36 + 40) }}>
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

          <Card title="Spend cube">
            <DataTable<CubeRow>
              rows={data.rows}
              columns={[
                ...data.dimensions.map((d) => ({ key: d, header: dimLabel(d), render: (r: CubeRow) => (r[d] == null ? <span className="text-slate-500">{UNASSIGNED}</span> : String(r[d])) })),
                { key: 'spendMinor', header: 'Spend', align: 'right' as const, render: (r: CubeRow) => inr(r.spendMinor) },
                { key: 'lines', header: 'Lines', align: 'right' as const },
                { key: 'contractCoveragePct', header: 'Contract coverage', align: 'right' as const, render: (r: CubeRow) => (r.contractCoveragePct === null ? '–' : `${r.contractCoveragePct}%`) },
              ]}
            />
          </Card>
        </>
      )}
    </div>
  );
}
