'use client';

import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Button, Card, DataTable, Dialog, Empty, Field, Input, Kpi, LinkButton, Loading, PageHeader, ProblemBox, Select, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, inr, label, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { useMe } from '../_components';

type Period = {
  id: string; period: string; method: string; statisticalQty: string; overrideQty: string | null; overrideReason: string | null;
  effectiveQty: string; actualQty: string | null; actualSource: string | null; released: boolean;
};
type MaterialForecast = { material: string; description: string; uom: string; plant: string; bias: string | null; mape: string | null; metricPeriods: string | null; periods: Period[] };
type Reference = { materials: { number: string; description: string; uom: string; type: string }[] };
type Recommendation = {
  id: string; agent: string; objectRef: string; title: string; rationale: string; proposal: Record<string, string>; deepLink: string | null;
  valueAtRiskMinor: number | null; status: string; createdAt: string;
};

const EFFECTIVE = '#1A56DB';
const ACTUAL = '#eb6834';

const monthLabel = (p: string) => new Date(Number(p.slice(0, 4)), Number(p.slice(5, 7)) - 1, 1).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });
const percent = (v: string | null) => (v === null ? '–' : `${(Number(v) * 100).toFixed(1)}%`);

function ForecastTooltip({ active, payload, uom }: { active?: boolean; payload?: { payload: { name: string; effective: number; statistical: number; actual: number | null; override: boolean } }[]; uom: string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
      <p className="font-semibold text-slate-900">{p.name}</p>
      <p className="tabular-nums text-slate-700">Forecast {qty(p.effective, uom)}{p.override ? ' (override)' : ''}</p>
      {p.override && <p className="tabular-nums text-slate-500">Statistical {qty(p.statistical, uom)}</p>}
      <p className="tabular-nums text-slate-700">Actual {p.actual === null ? 'not yet' : qty(p.actual, uom)}</p>
    </div>
  );
}

function ForecastReview() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const material = params.get('material') ?? '';
  const { scopes } = useMe();
  const canPlan = scopes.includes('mrp:plan');
  const ref = useApi<Reference>('/reference');
  const list = useApi<MaterialForecast[]>(`/forecasts${material ? `?material=${encodeURIComponent(material)}` : ''}`);
  const recs = useApi<Recommendation[]>('/recommendations');
  const sensing = (recs.data ?? []).filter((r) => r.agent === 'DEMAND_SENSING');
  const generate = useCommand(() => api.post<{ created: number; recommendations: number }>('/forecasts/generate'), {
    success: (r) => `Forecasts refreshed: ${r.created} new period(s), ${r.recommendations} demand-sensing recommendation(s)`,
  });
  const [overriding, setOverriding] = useState<{ f: MaterialForecast; p: Period } | null>(null);

  const setMaterial = (m: string) => router.replace(m ? `${pathname}?material=${encodeURIComponent(m)}` : pathname, { scroll: false });
  const materials = (ref.data?.materials ?? []).filter((m) => m.type === 'STOCK');

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="MRP-04 · Demand forecast review" title="Demand forecast review"
        subtitle="Statistical forecasts come from consumption. Overrides need a reason; only released periods become forecast demand that the next net-change MRP run plans against."
        actions={<>
          <LinkButton href="/pic/mrp">MRP console</LinkButton>
          {canPlan && <Button variant="primary" busy={generate.isPending} onClick={() => generate.mutate()}>Regenerate forecasts</Button>}
        </>} />
      {generate.error && <ProblemBox error={generate.error} />}

      <Card title="Material">
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Show forecasts for" hint="Deep links from the Demand Sensing Agent pre-select the material">{(id) => (
            <Select id={id} value={material} onChange={(e) => setMaterial(e.target.value)}
              options={[{ value: '', label: 'All forecast materials' }, ...materials.map((m) => ({ value: m.number, label: `${m.number} · ${m.description}` })),
                ...(material && !materials.some((m) => m.number === material) ? [{ value: material, label: material }] : [])]} />
          )}</Field>
        </div>
      </Card>

      <Card title={`Demand Sensing recommendations (${sensing.length})`}>
        {recs.isLoading ? <Loading /> : recs.error ? <ProblemBox error={recs.error} /> : !sensing.length ? (
          <Empty title="No open demand-sensing recommendations" hint="The agent proposes an override when forecast bias over the last three periods exceeds the tenant threshold." />
        ) : (
          <ul className="divide-y divide-slate-100">
            {sensing.map((r) => (
              <li key={r.id} className="flex flex-wrap items-start justify-between gap-3 py-3 first:pt-0 last:pb-0">
                <div className="min-w-0 max-w-3xl">
                  <p className="text-sm font-medium text-slate-900">{r.title}</p>
                  <p className="mt-0.5 text-sm text-slate-600">{r.rationale}</p>
                  <p className="mt-0.5 text-xs text-slate-500">{dateTime(r.createdAt)}{r.valueAtRiskMinor ? ` · value at risk ${inr(r.valueAtRiskMinor)}` : ''}</p>
                </div>
                {r.deepLink && <Link href={r.deepLink} className="text-sm font-medium text-[#1A56DB] hover:underline">Review {r.objectRef} →</Link>}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {list.isLoading ? <Loading /> : list.error ? <ProblemBox error={list.error} /> : !list.data?.length ? (
        <Empty title="No forecasts" hint={material ? `${material} has no forecast periods yet.` : 'Forecasts are generated from consumption history and goods issues.'} />
      ) : list.data.map((f) => (
        <MaterialCard key={`${f.material}-${f.plant}`} f={f} canPlan={canPlan} onOverride={(p) => setOverriding({ f, p })} />
      ))}

      {overriding && <OverrideDialog f={overriding.f} p={overriding.p} onClose={() => setOverriding(null)} />}
    </div>
  );
}

function MaterialCard({ f, canPlan, onOverride }: { f: MaterialForecast; canPlan: boolean; onOverride: (p: Period) => void }) {
  const chart = f.periods.map((p) => ({
    name: monthLabel(p.period), effective: Number(p.effectiveQty), statistical: Number(p.statisticalQty),
    actual: p.actualQty === null ? null : Number(p.actualQty), override: p.overrideQty !== null,
  }));
  const bias = f.bias === null ? null : Number(f.bias);
  const open = f.periods.filter((p) => p.actualQty === null);
  return (
    <Card title={<span>{f.material} · {f.description} <span className="font-normal text-slate-500">· plant {f.plant}</span></span>}>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label={`Bias (last ${f.metricPeriods ?? 3} periods)`} value={percent(f.bias)} hint={bias === null ? 'no actuals yet' : bias > 0 ? 'forecast above consumption' : bias < 0 ? 'forecast below consumption' : 'no bias'}
          tone={bias === null ? 'default' : Math.abs(bias) >= 0.15 ? 'bad' : Math.abs(bias) >= 0.05 ? 'warn' : 'good'} />
        <Kpi label={`MAPE (last ${f.metricPeriods ?? 3} periods)`} value={percent(f.mape)} tone={f.mape === null ? 'default' : Number(f.mape) >= 0.2 ? 'warn' : 'good'} />
        <Kpi label="Open periods" value={open.length} hint="without actual consumption" />
        <Kpi label="Released to MRP" value={`${f.periods.filter((p) => p.released).length} / ${f.periods.length}`} />
      </div>

      <div className="mt-4" style={{ height: 260 }} role="img" aria-label={`Line chart of forecast and actual consumption per month for ${f.material}; the table below lists the same values`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chart} margin={{ top: 8, right: 24, bottom: 4, left: 8 }}>
            <CartesianGrid vertical={false} stroke="#e2e8f0" />
            <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={{ stroke: '#cbd5e1' }} tickLine={false} interval="preserveStartEnd" minTickGap={16} />
            <YAxis tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} width={64}
              tickFormatter={(v: number) => (v >= 1e5 ? `${(v / 1e5).toFixed(1)} L` : v >= 1e3 ? `${(v / 1e3).toFixed(0)} k` : String(v))} />
            <Tooltip content={<ForecastTooltip uom={f.uom} />} cursor={{ stroke: '#94a3b8', strokeWidth: 1 }} />
            <Legend verticalAlign="top" height={28} wrapperStyle={{ fontSize: 12, color: '#334155' }} />
            <Line dataKey="effective" name={`Forecast (${f.uom})`} stroke={EFFECTIVE} strokeWidth={2} strokeDasharray="6 4" dot={{ r: 3, fill: EFFECTIVE, stroke: '#ffffff', strokeWidth: 1 }} isAnimationActive={false} />
            <Line dataKey="actual" name={`Actual (${f.uom})`} stroke={ACTUAL} strokeWidth={2} dot={{ r: 3, fill: ACTUAL, stroke: '#ffffff', strokeWidth: 1 }} isAnimationActive={false} connectNulls={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-4">
        <DataTable<Period> rows={f.periods} columns={[
          { key: 'period', header: 'Period', render: (p) => <span className="whitespace-nowrap">{monthLabel(p.period)}</span> },
          { key: 'method', header: 'Method', render: (p) => <span className="text-xs">{label(p.method)}</span> },
          { key: 'statisticalQty', header: 'Statistical', align: 'right', render: (p) => qty(p.statisticalQty) },
          { key: 'overrideQty', header: 'Override', align: 'right', render: (p) => (p.overrideQty === null ? '–' : (
            <span title={p.overrideReason ?? undefined}>{qty(p.overrideQty)}{p.overrideReason && <span className="block max-w-[200px] text-left text-xs text-slate-500">{p.overrideReason}</span>}</span>
          )) },
          { key: 'effectiveQty', header: 'Effective', align: 'right', render: (p) => <span className="font-semibold">{qty(p.effectiveQty, f.uom)}</span> },
          { key: 'actualQty', header: 'Actual', align: 'right', render: (p) => (p.actualQty === null ? '–' : qty(p.actualQty)) },
          { key: 'actualSource', header: 'Actual source', render: (p) => (p.actualSource ? <span className="text-xs">{label(p.actualSource)}</span> : '–') },
          { key: 'released', header: 'Released', render: (p) => (p.released ? '✓ Released' : 'Not released') },
          { key: 'actions', header: '', render: (p) => (canPlan && p.actualQty === null ? <PeriodActions f={f} p={p} onOverride={() => onOverride(p)} /> : null) },
        ]} />
        {!canPlan && <p className="mt-2 text-xs text-slate-500">Only an MRP controller can override or release forecasts.</p>}
      </div>
    </Card>
  );
}

function PeriodActions({ f, p, onOverride }: { f: MaterialForecast; p: Period; onOverride: () => void }) {
  const release = useCommand(() => api.post(`/forecasts/${p.id}/release`), {
    success: `${f.material} ${monthLabel(p.period)}: ${qty(p.effectiveQty, f.uom)} released as forecast demand for MRP`,
  });
  return (
    <div className="flex flex-wrap gap-1.5">
      <Button onClick={onOverride}>Override</Button>
      <Button variant="primary" busy={release.isPending} onClick={() => release.mutate()}>{p.released ? 'Re-release' : 'Release'}</Button>
    </div>
  );
}

function OverrideDialog({ f, p, onClose }: { f: MaterialForecast; p: Period; onClose: () => void }) {
  const [value, setValue] = useState(p.overrideQty ?? p.statisticalQty);
  const [reason, setReason] = useState('');
  const [release, setRelease] = useState(true);
  const valid = value !== '' && Number(value) >= 0 && reason.trim().length >= 5;
  const save = useCommand(() => api.post(`/forecasts/${p.id}/override`, { qty: value, reason: reason.trim(), release }), {
    success: `${f.material} ${monthLabel(p.period)} overridden to ${qty(value, f.uom)}${release ? ' and released to MRP' : ''}`, onSuccess: onClose });
  return (
    <Dialog open title={`Override forecast – ${f.material} · ${monthLabel(p.period)}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">Statistical forecast {qty(p.statisticalQty, f.uom)} ({label(p.method)}). Bias {percent(f.bias)}, MAPE {percent(f.mape)} over the last three periods.</p>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label={`Quantity (${f.uom})`}>{(id) => <Input id={id} type="number" min="0" step="1" value={value} onChange={(e) => setValue(e.target.value)} />}</Field>
        <div className="flex items-end">
          <label className="inline-flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" className="accent-[#1A56DB]" checked={release} onChange={(e) => setRelease(e.target.checked)} />
            Release to MRP now
          </label>
        </div>
        <div className="md:col-span-2">
          <Field label="Reason (required)" hint="At least 5 characters; kept in the material's audit trail.">{(id) => (
            <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Customer schedule cut by 8% from November (OEM call-off 2026-10-21)" />
          )}</Field>
        </div>
      </div>
      {save.error && <div className="mt-3"><ProblemBox error={save.error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!valid} busy={save.isPending} onClick={() => save.mutate()}>Save override</Button>
      </div>
    </Dialog>
  );
}

export default function ForecastReviewPage() {
  return <Suspense fallback={<Loading />}><ForecastReview /></Suspense>;
}
