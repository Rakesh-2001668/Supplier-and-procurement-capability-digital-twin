'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, PageHeader, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, inr, label, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

/** A hosted catalogue item (GET /catalogue-items): the CATALOGUE channel of guided buying (P03). */
type Item = {
  id: string; supplier: string | null; supplierName: string | null; supplier_part_no: string; description: string; material_group: string;
  category: string; uom: string; price_minor: number; currency: string; gst_rate: string; hsn_code: string | null; material: string | null;
  contract: string | null; valid_from: string | null; valid_to: string | null; lead_time_days: number | null; active: boolean; offeredToday: boolean;
};
type Reference = { suppliers: { code: string; name: string; status: string }[] };
type Me = { scopes: string[] };

const blank = {
  supplier: '', supplier_part_no: '', description: '', material_group: '', category: '', uom: 'EA', price: '', currency: 'INR', gst_rate: '18',
  hsn_code: '', material: '', contract: '', valid_from: '', valid_to: '', lead_time_days: '',
};
type Form = typeof blank;

export default function CatalogueMaintenance() {
  const [filter, setFilter] = useState({ q: '', active: 'true' });
  const query = new URLSearchParams({ ...(filter.q.trim() ? { q: filter.q.trim() } : {}), ...(filter.active ? { active: filter.active } : {}) });
  const items = useApi<Item[]>(`/catalogue-items?${query.toString()}`);
  const me = useApi<Me>('/me');
  const canMaintain = !!me.data?.scopes.some((s) => s === 'sourcing:manage' || s === 'contract:manage');
  const [editing, setEditing] = useState<Item | 'new' | null>(null);
  const [toggling, setToggling] = useState<Item | null>(null);
  const rows = (items.data ?? []) as (Item & Record<string, unknown>)[];

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="REQ-01 · Hosted catalogue" title="Catalogue maintenance"
        subtitle="Supplier parts offered in the CATALOGUE channel of guided buying, with their price validity, tax data and the contract that fixes the price. Bulk loads: python -m app.pic.tools.load_catalogue."
        actions={<>
          <Link href="/pic/buyer" className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-50">Buyer workbench</Link>
          {canMaintain && <Button variant="primary" onClick={() => setEditing('new')}>New item</Button>}
        </>} />
      <Card title={`Items (${rows.length})`} actions={<>
        <Input aria-label="Search description or part number" placeholder="Search" value={filter.q} onChange={(e) => setFilter({ ...filter, q: e.target.value })} />
        <Select aria-label="Status" value={filter.active} onChange={(e) => setFilter({ ...filter, active: e.target.value })}
          options={[{ value: 'true', label: 'Active' }, { value: 'false', label: 'Deactivated' }, { value: '', label: 'All' }]} />
      </>}>
        <DataTable<Item & Record<string, unknown>> rows={rows} loading={items.isLoading} error={items.error} empty="No catalogue items" columns={[
          { key: 'supplier', header: 'Supplier', render: (r) => <span title={r.supplierName ?? ''}>{r.supplier}</span> },
          { key: 'supplier_part_no', header: 'Part' },
          { key: 'description', header: 'Description', render: (r) => (
            <div><p>{r.description}</p><p className="text-xs text-slate-500">{r.material_group} · {r.category}{r.material ? ` · ${r.material}` : ''}</p></div>
          ) },
          { key: 'price_minor', header: 'Price', align: 'right', render: (r) => `${inr(r.price_minor)} / ${r.uom}` },
          { key: 'valid_from', header: 'Valid', render: (r) => `${r.valid_from ? date(r.valid_from) : 'open'} – ${r.valid_to ? date(r.valid_to) : 'open'}` },
          { key: 'contract', header: 'Contract', render: (r) => r.contract ?? '–' },
          { key: 'gst_rate', header: 'GST', align: 'right', render: (r) => `${r.gst_rate}%` },
          { key: 'offeredToday', header: 'Status', render: (r) => <StatusChip status={!r.active ? 'INACTIVE' : r.offeredToday ? 'ACTIVE' : 'NOT_VALID_TODAY'} /> },
          ...(canMaintain ? [{ key: 'actions', header: '', render: (r: Item) => (
            <div className="flex gap-2">
              <Button onClick={() => setEditing(r)}>Change</Button>
              <Button variant={r.active ? 'danger' : 'secondary'} onClick={() => setToggling(r)}>{r.active ? 'Deactivate' : 'Reactivate'}</Button>
            </div>
          ) }] : []),
        ]} />
      </Card>
      {editing && <ItemDialog item={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      {toggling && <ToggleDialog item={toggling} onClose={() => setToggling(null)} />}
    </div>
  );
}

function ItemDialog({ item, onClose }: { item: Item | null; onClose: () => void }) {
  const ref = useApi<Reference>('/reference');
  const [form, setForm] = useState<Form>(item ? {
    supplier: item.supplier ?? '', supplier_part_no: item.supplier_part_no, description: item.description, material_group: item.material_group,
    category: item.category, uom: item.uom, price: String(item.price_minor / 100), currency: item.currency, gst_rate: String(Number(item.gst_rate)),
    hsn_code: item.hsn_code ?? '', material: item.material ?? '', contract: item.contract ?? '', valid_from: item.valid_from ?? '',
    valid_to: item.valid_to ?? '', lead_time_days: item.lead_time_days != null ? String(item.lead_time_days) : '',
  } : blank);
  const [reason, setReason] = useState('');
  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));
  const payload = {
    description: form.description.trim(), material_group: form.material_group.trim(), category: form.category.trim() || undefined, uom: form.uom.trim(),
    price_minor: rupeesToMinor(form.price), currency: form.currency.trim() || 'INR', gst_rate: form.gst_rate || '18',
    hsn_code: form.hsn_code.trim() || null, material: form.material.trim() || null, contract: form.contract.trim() || null,
    valid_from: form.valid_from || null, valid_to: form.valid_to || null, lead_time_days: form.lead_time_days ? Number(form.lead_time_days) : null,
  };
  const changes: Record<string, unknown> = {};
  if (item) {
    const before: Record<string, unknown> = {
      description: item.description, material_group: item.material_group, category: item.category, uom: item.uom, price_minor: item.price_minor,
      currency: item.currency, gst_rate: String(Number(item.gst_rate)), hsn_code: item.hsn_code, material: item.material, contract: item.contract,
      valid_from: item.valid_from, valid_to: item.valid_to, lead_time_days: item.lead_time_days,
    };
    Object.entries(payload).forEach(([k, v]) => { if ((v ?? null) !== (before[k] ?? null) && !(k === 'category' && v === undefined)) changes[k] = v; });
  }
  const save = useCommand(() => (item
    ? api.patch<Item>(`/catalogue-items/${item.id}`, { changes, reason: reason.trim() })
    : api.post<Item>('/catalogue-items', { supplier: form.supplier, supplier_part_no: form.supplier_part_no.trim(), ...payload })), {
    success: (r) => `${r.supplier} ${r.supplier_part_no} saved`, onSuccess: onClose,
  });
  const invalid = !form.description.trim() || form.description.trim().length > 200 || !form.material_group.trim() || !form.uom.trim()
    || !(Number(form.price) > 0) || (!item && (!form.supplier || !form.supplier_part_no.trim()))
    || (!!form.valid_from && !!form.valid_to && form.valid_to < form.valid_from) || (!!item && (!Object.keys(changes).length || reason.trim().length < 3));
  return (
    <Dialog open wide title={item ? `Change ${item.supplier} ${item.supplier_part_no}` : 'New catalogue item'} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Supplier *">{(id) => (
          <Select id={id} value={form.supplier} disabled={!!item} onChange={(e) => set({ supplier: e.target.value })}
            options={[{ value: '', label: 'Choose a supplier' }, ...(ref.data?.suppliers ?? []).filter((s) => s.status !== 'BLOCKED')
              .map((s) => ({ value: s.code, label: `${s.code} · ${s.name}` }))]} />
        )}</Field>
        <Field label="Supplier part number *">{(id) => <Input id={id} maxLength={60} disabled={!!item} value={form.supplier_part_no} onChange={(e) => set({ supplier_part_no: e.target.value })} />}</Field>
        <Field label="Unit of measure *">{(id) => <Input id={id} maxLength={5} value={form.uom} onChange={(e) => set({ uom: e.target.value.toUpperCase() })} />}</Field>
        <div className="md:col-span-3"><Field label="Description *" hint={`${form.description.trim().length}/200 characters`}>{(id) => (
          <Input id={id} maxLength={200} value={form.description} onChange={(e) => set({ description: e.target.value })} />
        )}</Field></div>
        <Field label="Material group *">{(id) => <Input id={id} value={form.material_group} onChange={(e) => set({ material_group: e.target.value })} />}</Field>
        <Field label="Category" hint="Defaults to the material group">{(id) => <Input id={id} value={form.category} onChange={(e) => set({ category: e.target.value })} />}</Field>
        <Field label="Material (optional)">{(id) => <Input id={id} value={form.material} onChange={(e) => set({ material: e.target.value })} />}</Field>
        <Field label="Price per unit (₹) *">{(id) => <Input id={id} type="number" min="0" step="0.01" value={form.price} onChange={(e) => set({ price: e.target.value })} />}</Field>
        <Field label="GST rate %">{(id) => <Select id={id} value={form.gst_rate} onChange={(e) => set({ gst_rate: e.target.value })}
          options={['0', '0.25', '3', '5', '12', '18', '28'].map((v) => ({ value: v, label: `${v}%` }))} />}</Field>
        <Field label="HSN / SAC">{(id) => <Input id={id} value={form.hsn_code} onChange={(e) => set({ hsn_code: e.target.value })} />}</Field>
        <Field label="Valid from">{(id) => <Input id={id} type="date" value={form.valid_from} onChange={(e) => set({ valid_from: e.target.value })} />}</Field>
        <Field label="Valid to">{(id) => <Input id={id} type="date" value={form.valid_to} onChange={(e) => set({ valid_to: e.target.value })} />}</Field>
        <Field label="Lead time (days)">{(id) => <Input id={id} type="number" min="0" max="730" value={form.lead_time_days} onChange={(e) => set({ lead_time_days: e.target.value })} />}</Field>
        <Field label="Contract (optional)" hint="An active contract of the same supplier that fixes the price">{(id) => <Input id={id} value={form.contract} onChange={(e) => set({ contract: e.target.value })} />}</Field>
        {item && <div className="md:col-span-2"><Field label="Reason for the change *">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field></div>}
      </div>
      <div className="mt-3"><ProblemBox error={save.error} /></div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={save.isPending} disabled={invalid} onClick={() => save.mutate()}>{item ? 'Save change' : 'Create item'}</Button>
      </div>
    </Dialog>
  );
}

function ToggleDialog({ item, onClose }: { item: Item; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const action = item.active ? 'deactivate' : 'reactivate';
  const run = useCommand(() => api.post<Item>(`/catalogue-items/${item.id}/${action}`, { reason: reason.trim() }), {
    success: `${item.supplier_part_no} ${item.active ? 'deactivated' : 'reactivated'}`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`${label(action)} ${item.supplier} ${item.supplier_part_no}`} onClose={onClose}>
      <p className="text-sm text-slate-700">{item.active
        ? 'The item is no longer offered in guided buying and new requisition lines cannot use it; existing requisitions and orders keep it.'
        : 'The item is offered again within its price validity.'}</p>
      <div className="mt-3"><Field label="Reason *">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field></div>
      <div className="mt-3"><ProblemBox error={run.error} /></div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant={item.active ? 'danger' : 'primary'} busy={run.isPending} disabled={reason.trim().length < 3} onClick={() => run.mutate()}>{label(action)}</Button>
      </div>
    </Dialog>
  );
}
