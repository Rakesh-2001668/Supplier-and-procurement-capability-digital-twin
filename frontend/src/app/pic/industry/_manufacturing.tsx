'use client';

import { FormEvent, useState } from 'react';
import { Button, Card, DataTable, Field, Input, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { inr, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Card_ = { id: string; number: string; material: string; description: string; plant: string; storageLocation: string; binQty: string; uom: string;
  status: string; requisition: string | null; requisitionStatus: string | null; cycles: number; version: number };
type Parameter = { id: string; material: string; plant: string; reorder_point: string; max_stock: string | null; note: string | null };
type Open = { supplier: string; periodTo: string; totalMinor: number; lines: { contract: string; po: string; line: number; description: string; qty: string; unitPriceMinor: number; valueMinor: number }[] };

/** Kanban cards (BP M02-C1): an empty bin signals replenishment and raises a requisition. */
export function KanbanPanel({ canPlan }: { canPlan: boolean }) {
  const cards = useApi<Card_[]>('/kanban/cards');
  const [form, setForm] = useState({ material: '', plant: '', binQty: '' });
  const create = useCommand(() => api.post('/kanban/cards', { material: form.material.trim(), plant: form.plant.trim(), binQty: Number(form.binQty) }),
    { success: 'Kanban card created', onSuccess: () => setForm({ material: '', plant: '', binQty: '' }) });
  const act = useCommand((a: { card: Card_; action: string }) => api.post(`/kanban/cards/${a.card.number}/${a.action}`, a.action === 'suspend' || a.action === 'resume' ? { reason: 'Changed on the Kanban board' } : {},
    { ifMatch: `"${a.card.version}"` }), { success: (r) => `${(r as { number: string }).number} updated` });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };
  return (
    <Card title="Kanban cards">
      {canPlan && (
        <form onSubmit={submit} className="mb-4 grid gap-3 md:grid-cols-4 md:items-end">
          <Field label="Material">{(id) => <Input id={id} required value={form.material} onChange={(e) => setForm({ ...form, material: e.target.value })} />}</Field>
          <Field label="Plant">{(id) => <Input id={id} required value={form.plant} onChange={(e) => setForm({ ...form, plant: e.target.value })} />}</Field>
          <Field label="Bin quantity">{(id) => <Input id={id} required type="number" min="1" step="any" value={form.binQty} onChange={(e) => setForm({ ...form, binQty: e.target.value })} />}</Field>
          <Button type="submit" variant="primary" busy={create.isPending}>Create card</Button>
        </form>
      )}
      <DataTable<Card_>
        rows={cards.data ?? []} loading={cards.isLoading} error={cards.error} empty="No Kanban cards yet"
        columns={[
          { key: 'number', header: 'Card', render: (c) => <span className="font-medium">{c.number}</span> },
          { key: 'material', header: 'Material', render: (c) => `${c.material} · ${c.description}` },
          { key: 'plant', header: 'Plant / location', render: (c) => `${c.plant} / ${c.storageLocation}` },
          { key: 'binQty', header: 'Bin', align: 'right', render: (c) => qty(c.binQty, c.uom) },
          { key: 'status', header: 'Status', render: (c) => <StatusChip status={c.status} /> },
          { key: 'requisition', header: 'Requisition', render: (c) => c.requisition ? `${c.requisition} (${c.requisitionStatus})` : '–' },
          { key: 'cycles', header: 'Cycles', align: 'right' },
          { key: 'actions', header: 'Actions', render: (c) => canPlan ? (
            <div className="flex gap-1.5">
              {c.status === 'FULL' && <Button variant="primary" onClick={() => act.mutate({ card: c, action: 'signal' })}>Bin empty</Button>}
              {(c.status === 'EMPTY' || c.status === 'REPLENISHING') && <Button onClick={() => act.mutate({ card: c, action: 'refill' })}>Bin refilled</Button>}
              {c.status === 'FULL' && <Button variant="ghost" onClick={() => act.mutate({ card: c, action: 'suspend' })}>Suspend</Button>}
              {c.status === 'SUSPENDED' && <Button variant="ghost" onClick={() => act.mutate({ card: c, action: 'resume' })}>Resume</Button>}
            </div>
          ) : '–' },
        ]}
      />
    </Card>
  );
}

/** Reorder point and maximum stock (MRP type VB) and the planning mode of a material (daily, weekly, monthly buckets). */
export function ParameterPanel({ canPlan }: { canPlan: boolean }) {
  const params = useApi<Parameter[]>('/planning/parameters');
  const [form, setForm] = useState({ material: '', plant: '', reorderPoint: '', maxStock: '' });
  const [mode, setMode] = useState({ material: '', mrpType: 'PW' });
  const save = useCommand(() => api.put('/planning/parameters', { material: form.material.trim(), plant: form.plant.trim(), reorderPoint: Number(form.reorderPoint),
    maxStock: form.maxStock ? Number(form.maxStock) : null }), { success: 'Planning parameters saved' });
  const setType = useCommand(() => api.put(`/materials/${encodeURIComponent(mode.material.trim())}/mrp-type`, { mrpType: mode.mrpType }), { success: 'MRP type set' });
  return (
    <Card title="Reorder-point parameters and MRP type">
      {canPlan && (
        <div className="mb-4 grid gap-4 md:grid-cols-2">
          <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="grid gap-3 md:grid-cols-2 md:items-end">
            <Field label="Material">{(id) => <Input id={id} required value={form.material} onChange={(e) => setForm({ ...form, material: e.target.value })} />}</Field>
            <Field label="Plant">{(id) => <Input id={id} required value={form.plant} onChange={(e) => setForm({ ...form, plant: e.target.value })} />}</Field>
            <Field label="Reorder point">{(id) => <Input id={id} required type="number" min="0" step="any" value={form.reorderPoint} onChange={(e) => setForm({ ...form, reorderPoint: e.target.value })} />}</Field>
            <Field label="Maximum stock" hint="Order up to this quantity">{(id) => <Input id={id} type="number" min="0" step="any" value={form.maxStock} onChange={(e) => setForm({ ...form, maxStock: e.target.value })} />}</Field>
            <Button type="submit" variant="primary" busy={save.isPending}>Save parameters</Button>
          </form>
          <form onSubmit={(e) => { e.preventDefault(); setType.mutate(); }} className="grid gap-3 md:grid-cols-2 md:items-end">
            <Field label="Material">{(id) => <Input id={id} required value={mode.material} onChange={(e) => setMode({ ...mode, material: e.target.value })} />}</Field>
            <Field label="MRP type">{(id) => <Select id={id} value={mode.mrpType} onChange={(e) => setMode({ ...mode, mrpType: e.target.value })}
              options={[{ value: 'PD', label: 'PD · daily buckets' }, { value: 'PW', label: 'PW · weekly buckets' }, { value: 'PM', label: 'PM · monthly buckets' },
                { value: 'VB', label: 'VB · reorder point' }, { value: 'KB', label: 'KB · Kanban' }, { value: 'ND', label: 'ND · no planning' }]} />}</Field>
            <Button type="submit" busy={setType.isPending}>Set MRP type</Button>
          </form>
        </div>
      )}
      <DataTable<Parameter>
        rows={params.data ?? []} loading={params.isLoading} error={params.error} empty="No reorder-point parameters"
        columns={[{ key: 'material', header: 'Material' }, { key: 'plant', header: 'Plant' },
          { key: 'reorder_point', header: 'Reorder point', align: 'right', render: (r) => qty(r.reorder_point) },
          { key: 'max_stock', header: 'Maximum stock', align: 'right', render: (r) => r.max_stock ? qty(r.max_stock) : '–' }]}
      />
    </Card>
  );
}

/** Self-billing (ERS) on scheduling agreements: settle accepted call-off deliveries per period. */
export function SelfBillingPanel({ canSettle }: { canSettle: boolean }) {
  const [form, setForm] = useState({ supplier: '', periodTo: '' });
  const [asked, setAsked] = useState<{ supplier: string; periodTo: string } | null>(null);
  const preview = useApi<Open>(asked ? `/self-billing/open?supplier=${encodeURIComponent(asked.supplier)}&periodTo=${asked.periodTo}` : null);
  const settle = useCommand(() => api.post<{ number: string }>('/self-billing/settlements', { supplier: form.supplier.trim(), periodTo: form.periodTo }),
    { success: (r) => `ERS document ${r.number} created` });
  return (
    <Card title="Settle call-off deliveries (ERS)">
      <form onSubmit={(e) => { e.preventDefault(); setAsked({ supplier: form.supplier.trim(), periodTo: form.periodTo }); }} className="grid gap-3 md:grid-cols-4 md:items-end">
        <Field label="Supplier code">{(id) => <Input id={id} required value={form.supplier} onChange={(e) => setForm({ ...form, supplier: e.target.value })} />}</Field>
        <Field label="Settle up to">{(id) => <Input id={id} required type="date" value={form.periodTo} onChange={(e) => setForm({ ...form, periodTo: e.target.value })} />}</Field>
        <Button type="submit">Preview</Button>
        <Button type="button" variant="primary" busy={settle.isPending} disabled={!canSettle || !preview.data?.lines.length} onClick={() => settle.mutate()}>Create ERS document</Button>
      </form>
      {!canSettle && <p className="mt-2 text-xs text-slate-500">Accounts payable or finance settles; you can preview.</p>}
      {preview.error && <ProblemBox error={preview.error} />}
      {preview.data && (
        <div className="mt-4">
          <DataTable<Open['lines'][number]>
            rows={preview.data.lines} empty="Nothing to settle up to that date"
            columns={[{ key: 'contract', header: 'Agreement' }, { key: 'po', header: 'Order' }, { key: 'line', header: 'Line', align: 'right' },
              { key: 'description', header: 'Item' }, { key: 'qty', header: 'Quantity', align: 'right', render: (l) => qty(l.qty) },
              { key: 'unitPriceMinor', header: 'Price', align: 'right', render: (l) => inr(l.unitPriceMinor) },
              { key: 'valueMinor', header: 'Value', align: 'right', render: (l) => inr(l.valueMinor) }]}
          />
          <p className="mt-2 text-sm font-medium">Total {inr(preview.data.totalMinor)} before GST</p>
        </div>
      )}
    </Card>
  );
}
