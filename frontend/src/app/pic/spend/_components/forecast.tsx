'use client';

import { useState } from 'react';
import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card, DataTable, Empty, Facts, Field, Kpi, Loading, Select } from '@/components/pic/ui';
import { crore, inr } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { period, periodRange, rupeeTick, SpendProblem } from './shared';

type ForecastPoint = { period: string; actualMinor?: number; forecastMinor?: number; lowMinor?: number; highMinor?: number };
type Series = { category: string; method: string; next12Minor: number; points: ForecastPoint[] };
type SpendForecast = { history: [string, string]; horizon: string[]; series: Series[] };

const ACTUAL = '#1A56DB';
const FORECAST = '#eb6834';
const BAND = '#fbd5c4';

type Row = { period: string; label: string; actual: number | null; forecast: number | null; band: [number, number] | null; p: ForecastPoint };

function ForecastTooltip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  if (!active || !payload?.length) return null;
  const { p, label: name } = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
      <p className="font-semibold text-slate-900">{name}</p>
      {p.actualMinor !== undefined && <p className="tabular-nums text-slate-700">Actual {inr(p.actualMinor)}</p>}
      {p.forecastMinor !== undefined && (
        <>
          <p className="tabular-nums text-slate-700">Forecast {inr(p.forecastMinor)}</p>
          <p className="tabular-nums text-slate-500">80% band {inr(p.lowMinor)} – {inr(p.highMinor)}</p>
        </>
      )}
    </div>
  );
}

/** SPD-09 spend forecast per category: Holt linear smoothing with an 80% band. */
export function ForecastTab() {
  const [horizon, setHorizon] = useState('6');
  const [category, setCategory] = useState('');
  const { data, isLoading, error } = useApi<SpendForecast>(`/spend/forecast?horizon=${horizon}`);
  const series = data?.series ?? [];
  const current = series.find((s) => s.category === category) ?? series[0];

  const rows: Row[] = (current?.points ?? []).map((p) => ({
    period: p.period, label: period(p.period), p,
    actual: p.actualMinor !== undefined ? p.actualMinor / 100 : null,
    forecast: p.forecastMinor !== undefined ? p.forecastMinor / 100 : null,
    band: p.lowMinor !== undefined && p.highMinor !== undefined ? [p.lowMinor / 100, p.highMinor / 100] : null,
  }));
  // Join the forecast to the last actual so the two lines meet.
  const lastActual = rows.map((r) => r.actual !== null).lastIndexOf(true);
  if (lastActual >= 0 && rows[lastActual + 1]?.forecast !== null) {
    const a = rows[lastActual].actual as number;
    rows[lastActual] = { ...rows[lastActual], forecast: a, band: [a, a] };
  }
  const horizonTotal = (current?.points ?? []).reduce((s, p) => s + (p.forecastMinor ?? 0), 0);
  const last12 = (current?.points ?? []).reduce((s, p) => s + (p.actualMinor ?? 0), 0);

  return (
    <div className="space-y-6">
      <Card title="Forecast settings">
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Category">{(id) => (
            <Select id={id} value={current?.category ?? ''} onChange={(e) => setCategory(e.target.value)}
              options={series.length ? series.map((s) => ({ value: s.category, label: `${s.category} · ${crore(s.next12Minor)} next 12 months` })) : [{ value: '', label: isLoading ? 'Loading…' : 'No categories' }]} />
          )}</Field>
          <Field label="Horizon">{(id) => (
            <Select id={id} value={horizon} onChange={(e) => setHorizon(e.target.value)}
              options={[{ value: '3', label: '3 months' }, { value: '6', label: '6 months' }, { value: '12', label: '12 months' }]} />
          )}</Field>
        </div>
      </Card>

      {isLoading ? <Loading /> : error ? <SpendProblem error={error} /> : !current ? (
        <Empty title="Not enough history to forecast" hint="A category needs at least three months with posted spend." />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Last 12 months" value={crore(last12)} hint="actual posted spend" />
            <Kpi label={`Next ${horizon} months`} value={crore(horizonTotal)} hint="forecast midpoint" />
            <Kpi label="Next 12 months" value={crore(current.next12Minor)} hint="used as the category plan budget" />
            <Kpi label="Change" value={last12 ? `${(((current.next12Minor - last12) * 100) / last12).toFixed(1)}%` : '–'} hint="next 12 vs last 12"
              tone={current.next12Minor > last12 ? 'warn' : 'good'} />
          </div>

          <Card title={`${current.category} · actual and forecast spend`}>
            <div style={{ height: 320 }} role="img" aria-label={`Line chart of monthly actual spend and forecast with an 80% band for ${current.category}; the table below lists the same values`}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={rows} margin={{ top: 8, right: 24, bottom: 4, left: 8 }}>
                  <CartesianGrid vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={{ stroke: '#cbd5e1' }} tickLine={false} interval="preserveStartEnd" minTickGap={16} />
                  <YAxis tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} width={72} tickFormatter={rupeeTick} />
                  <Tooltip content={<ForecastTooltip />} cursor={{ stroke: '#94a3b8', strokeWidth: 1 }} />
                  <Legend verticalAlign="top" height={28} wrapperStyle={{ fontSize: 12, color: '#334155' }} />
                  <Area dataKey="band" name="80% band" fill={BAND} stroke="none" fillOpacity={0.8} isAnimationActive={false} connectNulls={false} />
                  <Line dataKey="actual" name="Actual" stroke={ACTUAL} strokeWidth={2} dot={{ r: 3, fill: ACTUAL, stroke: '#ffffff', strokeWidth: 1 }} isAnimationActive={false} connectNulls={false} />
                  <Line dataKey="forecast" name="Forecast" stroke={FORECAST} strokeWidth={2} strokeDasharray="6 4" dot={{ r: 3, fill: FORECAST, stroke: '#ffffff', strokeWidth: 1 }} isAnimationActive={false} connectNulls={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-4">
              <Facts items={[
                ['Method', current.method],
                ['History', periodRange(data?.history)],
                ['Horizon', data?.horizon.length ? `${period(data.horizon[0])} – ${period(data.horizon[data.horizon.length - 1])}` : '–'],
                ['Categories forecast', String(series.length)],
              ]} />
            </div>
          </Card>

          <Card title="Monthly values">
            <DataTable<ForecastPoint & { id: string }> rows={current.points.map((p) => ({ ...p, id: p.period }))} columns={[
              { key: 'period', header: 'Period', render: (p) => period(p.period) },
              { key: 'actualMinor', header: 'Actual', align: 'right', render: (p) => (p.actualMinor !== undefined ? inr(p.actualMinor) : '–') },
              { key: 'forecastMinor', header: 'Forecast', align: 'right', render: (p) => (p.forecastMinor !== undefined ? inr(p.forecastMinor) : '–') },
              { key: 'lowMinor', header: 'Low (10%)', align: 'right', render: (p) => (p.lowMinor !== undefined ? inr(p.lowMinor) : '–') },
              { key: 'highMinor', header: 'High (90%)', align: 'right', render: (p) => (p.highMinor !== undefined ? inr(p.highMinor) : '–') },
            ]} />
          </Card>
        </>
      )}
    </div>
  );
}
