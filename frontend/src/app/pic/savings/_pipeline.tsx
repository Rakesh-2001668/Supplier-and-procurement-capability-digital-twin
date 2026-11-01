'use client';

import { useCallback, useState } from 'react';
import { Card, DataTable, Empty, Field, Input, Kpi, Loading, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { SavedViews } from '@/components/pic/views';
import { crore, inr, label } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';

type Item = { id: string; number: string; title: string; category: string; stage: string; owner: string | null; forecastMinor: number; forecastBasis: string;
  negotiatedMinor: number; avoidanceMinor: number; realisedMinor: number; realisationPct: string | null; gapMinor: number; validated: boolean } & Record<string, unknown>;
type Stage = { stage: string; count: number; forecastMinor: number; negotiatedMinor: number; avoidanceMinor: number; realisedMinor: number; realisationPct: string | null } & Record<string, unknown>;
type Pipeline = {
  stages: Stage[]; initiatives: Item[]; funnel: Record<string, number>; categories: string[]; owners: { id: string; name: string | null }[];
  totals: { initiatives: number; forecastMinor: number; negotiatedMinor: number; avoidanceMinor: number; realisedMinor: number; lostMinor: number; realisationPct: string | null };
};
type Filters = { stage: string; category: string; owner: string; createdFrom: string; createdTo: string };
const NONE: Filters = { stage: '', category: '', owner: '', createdFrom: '', createdTo: '' };
const STAGES = ['IDENTIFIED', 'NEGOTIATED', 'CONTRACTED', 'REALISING', 'VALIDATED', 'LOST'];

/** SPD-08 Savings & pipeline tracker: forecast vs realised savings and cost avoidance by stage and initiative. */
export function PipelineTab() {
  const [filters, setFilters] = useState<Filters>(NONE);
  const apply = useCallback((f: Record<string, unknown>) => setFilters({ ...NONE, ...(f as Partial<Filters>) }), []);
  const query = new URLSearchParams();
  if (filters.stage) query.set('stage', filters.stage);
  if (filters.category) query.set('category', filters.category);
  if (filters.owner) query.set('owner', filters.owner);
  if (filters.createdFrom) query.set('created_from', filters.createdFrom);
  if (filters.createdTo) query.set('created_to', filters.createdTo);
  const { data, isLoading, error } = useApi<Pipeline>(`/savings/pipeline${query.size ? `?${query.toString()}` : ''}`);
  // The filter options come from an unfiltered call so they do not shrink as the filters narrow.
  const all = useApi<Pipeline>('/savings/pipeline');

  return (
    <div className="space-y-6">
      <Card title="Filters" actions={<SavedViews screen="savings-pipeline" filters={filters} onApply={apply} />}>
        <div className="grid gap-3 md:grid-cols-5">
          <Field label="Stage">{(id) => <Select id={id} value={filters.stage} onChange={(e) => setFilters({ ...filters, stage: e.target.value })}
            options={[{ value: '', label: 'All stages' }, ...STAGES.map((s) => ({ value: s, label: label(s) }))]} />}</Field>
          <Field label="Category">{(id) => <Select id={id} value={filters.category} onChange={(e) => setFilters({ ...filters, category: e.target.value })}
            options={[{ value: '', label: 'All categories' }, ...(all.data?.categories ?? []).map((c) => ({ value: c, label: c }))]} />}</Field>
          <Field label="Owner">{(id) => <Select id={id} value={filters.owner} onChange={(e) => setFilters({ ...filters, owner: e.target.value })}
            options={[{ value: '', label: 'Anyone' }, ...(all.data?.owners ?? []).map((o) => ({ value: o.id, label: o.name ?? o.id }))]} />}</Field>
          <Field label="Created from">{(id) => <Input id={id} type="date" value={filters.createdFrom} onChange={(e) => setFilters({ ...filters, createdFrom: e.target.value })} />}</Field>
          <Field label="Created to">{(id) => <Input id={id} type="date" value={filters.createdTo} onChange={(e) => setFilters({ ...filters, createdTo: e.target.value })} />}</Field>
        </div>
      </Card>

      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : !data ? null : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Kpi label="Forecast (annual)" value={crore(data.totals.forecastMinor)} hint="negotiated, else target" />
            <Kpi label="Negotiated" value={crore(data.totals.negotiatedMinor)} hint="never counts toward budget" />
            <Kpi label="Cost avoidance" value={crore(data.totals.avoidanceMinor)} hint="never counts toward budget" />
            <Kpi label="Realised" value={crore(data.totals.realisedMinor)} hint="posted invoices only" tone="good" />
            <Kpi label="Realisation" value={data.totals.realisationPct === null ? '–' : `${data.totals.realisationPct}%`} hint={`lost ${crore(data.totals.lostMinor)}`} />
          </div>

          <Card title="By stage">
            <DataTable<Stage> caption="Savings by pipeline stage" rows={data.stages} columns={[
              { key: 'stage', header: 'Stage', render: (r) => <StatusChip status={r.stage} /> },
              { key: 'count', header: 'Initiatives', align: 'right' },
              { key: 'forecastMinor', header: 'Forecast', align: 'right', render: (r) => inr(r.forecastMinor) },
              { key: 'negotiatedMinor', header: 'Negotiated', align: 'right', render: (r) => inr(r.negotiatedMinor) },
              { key: 'avoidanceMinor', header: 'Avoidance', align: 'right', render: (r) => inr(r.avoidanceMinor) },
              { key: 'realisedMinor', header: 'Realised', align: 'right', render: (r) => inr(r.realisedMinor) },
              { key: 'realisationPct', header: 'Realised / negotiated', align: 'right', render: (r) => (r.realisationPct === null ? '–' : `${r.realisationPct}%`) },
            ]} />
            <p className="mt-3 text-xs text-slate-600">
              Funnel (initiatives that reached each stage): {Object.entries(data.funnel).map(([k, v]) => `${label(k)} ${v}`).join(' → ')}
            </p>
          </Card>

          <Card title="Initiatives">
            {data.initiatives.length === 0 ? <Empty title="No initiative matches these filters" /> : (
              <DataTable<Item> caption="Savings initiatives with forecast and realised savings" rows={data.initiatives} columns={[
                { key: 'number', header: 'Initiative', render: (r) => <span className="font-mono font-medium">{r.number}</span> },
                { key: 'title', header: 'Title', className: 'min-w-[200px]' },
                { key: 'category', header: 'Category' },
                { key: 'stage', header: 'Stage', render: (r) => <StatusChip status={r.stage} /> },
                { key: 'owner', header: 'Owner', render: (r) => r.owner ?? '–' },
                { key: 'forecastMinor', header: 'Forecast', align: 'right', render: (r) => <span>{inr(r.forecastMinor)}<br /><span className="text-xs text-slate-500">{label(r.forecastBasis)}</span></span> },
                { key: 'avoidanceMinor', header: 'Avoidance', align: 'right', render: (r) => inr(r.avoidanceMinor) },
                { key: 'realisedMinor', header: 'Realised', align: 'right', render: (r) => inr(r.realisedMinor) },
                { key: 'gapMinor', header: 'Gap to forecast', align: 'right', render: (r) => inr(r.gapMinor) },
                { key: 'validated', header: 'Validated', render: (r) => (r.validated ? '✓ Yes' : 'No') },
              ]} />
            )}
          </Card>
        </>
      )}
    </div>
  );
}
