'use client';

import { useState } from 'react';
import { Card, Button, DataTable, Empty, Field, Input, Kpi, Loading, ProblemBox, Select } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { useMe } from '../../mrp/_components';
import { period, SpendProblem } from './shared';

type Accuracy = {
  count: number; mapePct: number | null; biasPct?: number | null; bandCoveragePct: number | null; byHorizon: { horizon: number; mapePct: number | null; count: number }[];
  series: { category: string; mapePct: number | null; count: number }[]; lastComplete?: string;
};

/** Forecasts as they were issued, judged against the spend that happened; and the action that stores today's forecast as a snapshot. */
export function ForecastAccuracy() {
  const { scopes } = useMe();
  const [category, setCategory] = useState('');
  const [horizon, setHorizon] = useState('6');
  const { data, isLoading, error } = useApi<Accuracy>(`/spend/forecast/accuracy${category.trim() ? `?category=${encodeURIComponent(category.trim())}` : ''}`);
  const snapshot = useCommand(() => api.post<{ asOf: string; rows: number; series: number }>(`/spend/forecast/snapshot?horizon=${horizon}`, {}), {
    success: (r) => `Snapshot stored as of ${period(r.asOf)}: ${r.rows.toLocaleString('en-IN')} forecast month(s) over ${r.series} series`,
  });
  const canSnapshot = scopes.includes('savings:manage');
  const pctText = (v: number | null | undefined) => (v === null || v === undefined ? '–' : `${v}%`);

  return (
    <Card title="Forecast accuracy" actions={<span className="text-xs text-slate-500">issued forecasts vs what was spent</span>}>
      <div className="space-y-4">
        <p className="text-sm text-slate-600">
          Each month the forecast is stored as issued (a snapshot). When the month closes, it is compared with the posted spend: the mean absolute percentage error (MAPE) overall and per horizon,
          the bias (positive means the forecast ran high) and how often the actual fell inside the 80% band.
        </p>
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Category (blank: all)">{(id) => <Input id={id} value={category} onChange={(e) => setCategory(e.target.value.toUpperCase())} />}</Field>
          {canSnapshot && (
            <>
              <Field label="Snapshot horizon">{(id) => <Select id={id} value={horizon} onChange={(e) => setHorizon(e.target.value)}
                options={[3, 6, 9, 12].map((n) => ({ value: String(n), label: `${n} months` }))} />}</Field>
              <div className="flex items-end"><Button variant="primary" busy={snapshot.isPending} onClick={() => snapshot.mutate()}>Store forecast snapshot</Button></div>
            </>
          )}
        </div>
        {snapshot.error && <ProblemBox error={snapshot.error} />}
        {isLoading ? <Loading /> : error ? <SpendProblem error={error} /> : !data || data.count === 0 ? (
          <Empty title="No closed month to judge yet" hint="Accuracy appears once a stored forecast month has closed. Store a snapshot now and come back after month end." />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Kpi label="MAPE" value={pctText(data.mapePct)} hint={`${data.count.toLocaleString('en-IN')} judged forecast months`} tone={data.mapePct !== null && data.mapePct > 20 ? 'warn' : 'good'} />
              <Kpi label="Bias" value={pctText(data.biasPct)} hint="positive: forecast ran high" />
              <Kpi label="Inside the 80% band" value={pctText(data.bandCoveragePct)} hint="target about 80%" />
              <Kpi label="Judged up to" value={data.lastComplete ? period(data.lastComplete) : '–'} hint="last complete month" />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <DataTable<Accuracy['byHorizon'][number] & { id: string }> caption="Forecast error by horizon" rows={data.byHorizon.map((h) => ({ ...h, id: String(h.horizon) }))} columns={[
                { key: 'horizon', header: 'Months ahead', render: (h) => `${h.horizon}` },
                { key: 'mapePct', header: 'MAPE', align: 'right', render: (h) => pctText(h.mapePct) },
                { key: 'count', header: 'Forecasts judged', align: 'right' },
              ]} />
              <DataTable<Accuracy['series'][number] & { id: string }> caption="Forecast error by category" rows={data.series.map((s) => ({ ...s, id: s.category }))} columns={[
                { key: 'category', header: 'Category', render: (s) => <span className="font-mono text-xs font-semibold">{s.category}</span> },
                { key: 'mapePct', header: 'MAPE', align: 'right', render: (s) => pctText(s.mapePct) },
                { key: 'count', header: 'Forecasts judged', align: 'right' },
              ]} />
            </div>
          </>
        )}
      </div>
    </Card>
  );
}
