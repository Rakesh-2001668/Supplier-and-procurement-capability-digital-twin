'use client';

import { FormEvent, useState } from 'react';
import { Button, Card, Dialog, Empty, Field, Input, Kpi, LinkButton, Loading, PageHeader, ProblemBox, Select, Textarea } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { date, inr, label, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { MANAGE_ROLES, useCan } from '../_lib';

type Band = { points: Record<string, { priceMinor: number; source: string; asOf?: string; orderLines?: number; since?: string }>; lowMinor: number | null; highMinor: number | null; medianMinor: number | null };

function RecordDialog({ category, material, onClose }: { category: string; material: string; onClose: () => void }) {
  const [d, setD] = useState({ category, material, kind: 'MARKET', as_of: new Date().toISOString().slice(0, 10), price: '', uom: 'EA', source: '', note: '' });
  const [error, setError] = useState<ApiError | null>(null);
  const set = (patch: Partial<typeof d>) => setD((cur) => ({ ...cur, ...patch }));
  const ok = d.category.trim() && Number(d.price) > 0 && d.uom.trim() && d.source.trim().length >= 2 && d.as_of;
  const save = useCommand(() => api.post('/sourcing/benchmarks', {
    category: d.category.trim().toUpperCase(), material: d.material.trim() || undefined, kind: d.kind, as_of: d.as_of, price_minor: rupeesToMinor(d.price), uom: d.uom.trim().toUpperCase(),
    source: d.source.trim(), note: d.note.trim() || undefined,
  }), { success: 'Benchmark recorded', onSuccess: onClose });
  return (
    <Dialog open title="Record a market or peer price" onClose={onClose}>
      <div className="space-y-3">
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Category" required>{(id) => <Input id={id} value={d.category} onChange={(e) => set({ category: e.target.value.toUpperCase() })} />}</Field>
          <Field label="Material number" hint="Empty: a category-level price">{(id) => <Input id={id} value={d.material} onChange={(e) => set({ material: e.target.value })} />}</Field>
          <Field label="Kind">{(id) => <Select id={id} value={d.kind} onChange={(e) => set({ kind: e.target.value })} options={[{ value: 'MARKET', label: 'Market quote' }, { value: 'PEER', label: 'Peer price' }, { value: 'CATALOGUE', label: 'Catalogue price' }]} />}</Field>
          <Field label="As of" required>{(id) => <Input id={id} type="date" value={d.as_of} onChange={(e) => set({ as_of: e.target.value })} />}</Field>
          <Field label="Price per unit (₹)" required>{(id) => <Input id={id} type="number" min="0" step="0.01" value={d.price} onChange={(e) => set({ price: e.target.value })} />}</Field>
          <Field label="Unit of measure" required>{(id) => <Input id={id} maxLength={5} value={d.uom} onChange={(e) => set({ uom: e.target.value })} />}</Field>
        </div>
        <Field label="Source" hint="Who quoted it, e.g. a trade index, a peer group, a supplier catalogue" required>{(id) => <Input id={id} value={d.source} maxLength={80} onChange={(e) => set({ source: e.target.value })} />}</Field>
        <Field label="Note">{(id) => <Textarea id={id} value={d.note} onChange={(e) => set({ note: e.target.value })} />}</Field>
        <ProblemBox error={error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!ok} busy={save.isPending} onClick={() => save.mutate(undefined, { onError: (e) => setError(e) })}>Record</Button>
        </div>
      </div>
    </Dialog>
  );
}

export default function BenchmarksPage() {
  const can = useCan();
  const canManage = can(MANAGE_ROLES);
  const [form, setForm] = useState({ category: '', material: '', on: '' });
  const [query, setQuery] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const band = useApi<Band>(query);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!form.category.trim()) return;
    const q = new URLSearchParams({ category: form.category.trim().toUpperCase() });
    if (form.material.trim()) q.set('material', form.material.trim());
    if (form.on) q.set('on', form.on);
    setQuery(`/sourcing/benchmarks?${q.toString()}`);
  };
  const points = Object.entries(band.data?.points ?? {});
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="SRC-03 · Benchmarks" title="Price benchmarks"
        subtitle="Every reference price PIC holds for an item and the band they span: the last price, the quantity-weighted average of the last 12 months of orders, the latest market quote and peer or catalogue prices."
        actions={<>
          <LinkButton href="/pic/sourcing">Back to sourcing</LinkButton>
          {canManage && <Button onClick={() => setRecording(true)}>Record a price</Button>}
        </>} />
      <Card title="Look up">
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-4">
          <Field label="Category" required hint="e.g. ALU-DIECAST">{(id) => <Input id={id} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value.toUpperCase() })} />}</Field>
          <Field label="Material number" hint="Optional">{(id) => <Input id={id} value={form.material} onChange={(e) => setForm({ ...form, material: e.target.value })} />}</Field>
          <Field label="As of" hint="Empty: today">{(id) => <Input id={id} type="date" value={form.on} onChange={(e) => setForm({ ...form, on: e.target.value })} />}</Field>
          <div className="flex items-end"><Button type="submit" variant="primary" disabled={!form.category.trim()}>Show benchmarks</Button></div>
        </form>
      </Card>
      {query && (band.isLoading ? <Loading /> : band.error ? <ProblemBox error={band.error} /> : band.data && (
        points.length === 0 ? <Empty title="No reference price held" hint="Record a market or peer price, or load orders for the material." /> : (
          <div className="space-y-4" aria-live="polite">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Kpi label="Low" value={inr(band.data.lowMinor)} tone="good" />
              <Kpi label="Median" value={inr(band.data.medianMinor)} />
              <Kpi label="High" value={inr(band.data.highMinor)} tone="warn" />
              <Kpi label="Reference points" value={points.length} hint="a bid inside the band is plausible" />
            </div>
            <Card title="Reference prices">
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <caption className="sr-only">Reference prices and their source</caption>
                  <thead className="text-left text-xs uppercase tracking-wide text-slate-500"><tr><th scope="col" className="py-1 pr-3">Reference</th><th scope="col" className="py-1 pr-3 text-right">Price per unit</th><th scope="col" className="py-1 pr-3">Source</th><th scope="col" className="py-1">As of</th></tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {points.map(([k, p]) => (
                      <tr key={k}><th scope="row" className="py-1 pr-3 text-left font-medium">{label(k)}</th><td className="py-1 pr-3 text-right tabular-nums">{inr(p.priceMinor)}</td>
                        <td className="py-1 pr-3">{p.source}{p.orderLines ? ` · ${p.orderLines} order line(s)` : ''}</td><td className="py-1">{p.asOf ? date(p.asOf) : p.since ? `since ${date(p.since)}` : '–'}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        )
      ))}
      {recording && <RecordDialog category={form.category.trim().toUpperCase()} material={form.material.trim()} onClose={() => { setRecording(false); if (query) band.refetch(); }} />}
    </div>
  );
}
