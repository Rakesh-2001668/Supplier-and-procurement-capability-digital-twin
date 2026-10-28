'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, PageHeader, ProblemBox, Select, StatusChip, Tabs, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, label } from '@/lib/pic/format';
import { useApi, useCommand, useList } from '@/lib/pic/hooks';

type Material = { id: string; number: string; description: string; type: string; material_group: string | null; category: string | null;
  base_uom: string; hsn_code: string | null; gst_rate: string | null; mpn: string | null; status: string; erp_synced: boolean; created_at: string };
type MaterialRequest = { id: string; number: string; status: string; description: string; type: string; material_group: string;
  category: string; base_uom: string; duplicate_score: string | null; created_at: string };
type Me = { scopes: string[] };

const REQUEST_STATUSES = ['', 'DRAFT', 'DUPLICATE_CHECK', 'DUPLICATE_BLOCKED', 'IN_STEWARDSHIP', 'APPROVED', 'SYNCED_TO_ERP', 'MERGED', 'REJECTED'];
const MATERIAL_TYPES = ['NON_STOCK', 'STOCK', 'SERVICE'];

export default function Materials() {
  const [open, setOpen] = useState(false);
  const me = useApi<Me>('/me');
  const canRequest = !!me.data?.scopes.includes('req:create');
  return (
    <div>
      <PageHeader eyebrow="MDM-01 / MDM-02 / MDM-03 · Material master governance" title="Materials"
        subtitle="Every new material is duplicate-checked (description, classification, MPN, attributes) and approved by a data steward before it is synced to ERP."
        actions={canRequest ? <Button variant="primary" onClick={() => setOpen(true)}>New material request</Button> : undefined} />
      <Card>
        <Tabs tabs={[
          { id: 'materials', label: 'Materials', content: <MaterialList /> },
          { id: 'requests', label: 'Material requests', content: <RequestList /> },
        ]} />
      </Card>
      {open && <NewRequestDialog onClose={() => setOpen(false)} />}
    </div>
  );
}

function MaterialList() {
  const list = useList<Material>('/materials');
  return (
    <DataTable<Material>
      rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
      loadingMore={list.isFetchingNextPage} empty="No materials"
      columns={[
        { key: 'number', header: 'Material', render: (m) => <span className="font-medium">{m.number}</span> },
        { key: 'description', header: 'Description' },
        { key: 'type', header: 'Type', render: (m) => label(m.type) },
        { key: 'material_group', header: 'Material group', render: (m) => m.material_group ?? '–' },
        { key: 'category', header: 'Category', render: (m) => m.category ?? '–' },
        { key: 'base_uom', header: 'UoM' },
        { key: 'hsn_code', header: 'HSN', render: (m) => m.hsn_code ?? '–' },
        { key: 'mpn', header: 'MPN', render: (m) => m.mpn ?? '–' },
        { key: 'status', header: 'Status', render: (m) => <StatusChip status={m.status} /> },
        { key: 'erp_synced', header: 'ERP', render: (m) => (m.erp_synced ? 'Synced' : 'Pending sync') },
      ]}
    />
  );
}

function RequestList() {
  const [status, setStatus] = useState('');
  const list = useList<MaterialRequest>(`/materials/requests${status ? `?status=${status}` : ''}`);
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Select aria-label="Filter requests by status" value={status} onChange={(e) => setStatus(e.target.value)} className="max-w-xs"
          options={REQUEST_STATUSES.map((s) => ({ value: s, label: s ? label(s) : 'All statuses' }))} />
      </div>
      <DataTable<MaterialRequest>
        rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
        loadingMore={list.isFetchingNextPage} rowHref={(r) => `/pic/materials/${r.number}`} empty="No material requests"
        columns={[
          { key: 'number', header: 'Request' },
          { key: 'description', header: 'Description' },
          { key: 'type', header: 'Type', render: (r) => label(r.type) },
          { key: 'material_group', header: 'Material group' },
          { key: 'category', header: 'Category' },
          { key: 'duplicate_score', header: 'Duplicate score', align: 'right', render: (r) => r.duplicate_score != null ? `${Math.round(Number(r.duplicate_score) * 100)}%` : '–' },
          { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
          { key: 'created_at', header: 'Requested', render: (r) => date(r.created_at) },
        ]}
      />
    </div>
  );
}

function NewRequestDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [form, setForm] = useState({ description: '', type: 'NON_STOCK', material_group: '', category: '', base_uom: 'EA', valuation_class: '', hsn_code: '', mpn: '' });
  const [attributes, setAttributes] = useState('');
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const parsed: Record<string, string> = {};
  const badLines: string[] = [];
  attributes.split('\n').map((l) => l.trim()).filter(Boolean).forEach((l) => {
    const i = l.indexOf('=');
    if (i <= 0) badLines.push(l);
    else parsed[l.slice(0, i).trim()] = l.slice(i + 1).trim();
  });
  const missing = !form.description.trim() || !form.material_group.trim() || !form.category.trim() || !form.base_uom.trim();

  const create = useCommand(() => api.post<{ number: string; status: string }>('/materials/requests', {
    description: form.description.trim(), type: form.type, material_group: form.material_group.trim(), category: form.category.trim(),
    base_uom: form.base_uom.trim().toUpperCase(), valuation_class: form.valuation_class.trim() || undefined, hsn_code: form.hsn_code.trim() || undefined,
    mpn: form.mpn.trim() || undefined, attributes: Object.keys(parsed).length ? parsed : undefined,
  }), { success: (r) => `${r.number}: ${label(r.status)}`, onSuccess: (r) => router.push(`/pic/materials/${r.number}`) });

  return (
    <Dialog open title="New material request" onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="md:col-span-2"><Field label="Description *">{(id) => <Input id={id} value={form.description} onChange={set('description')} />}</Field></div>
        <Field label="Material type">{(id) => <Select id={id} value={form.type} onChange={set('type')} options={MATERIAL_TYPES.map((t) => ({ value: t, label: label(t) }))} />}</Field>
        <Field label="Base unit of measure *">{(id) => <Input id={id} value={form.base_uom} onChange={set('base_uom')} />}</Field>
        <Field label="Material group *">{(id) => <Input id={id} value={form.material_group} onChange={set('material_group')} />}</Field>
        <Field label="Category *">{(id) => <Input id={id} value={form.category} onChange={set('category')} />}</Field>
        <Field label="Valuation class">{(id) => <Input id={id} value={form.valuation_class} onChange={set('valuation_class')} />}</Field>
        <Field label="HSN code">{(id) => <Input id={id} value={form.hsn_code} onChange={set('hsn_code')} />}</Field>
        <Field label="Manufacturer part number (MPN)">{(id) => <Input id={id} value={form.mpn} onChange={set('mpn')} />}</Field>
        <div className="md:col-span-2">
          <Field label="Attributes" hint="One per line as name=value, e.g. alloy=ADC12">{(id) => <Textarea id={id} value={attributes} onChange={(e) => setAttributes(e.target.value)} />}</Field>
          {badLines.length > 0 && <p className="mt-1 text-xs text-red-700">Not in name=value form: {badLines.join(', ')}</p>}
        </div>
      </div>
      <p className="mt-3 text-xs text-slate-500">The request is duplicate-checked immediately. A high match blocks it until it is merged into the existing material or a steward overrides the block.</p>
      <div className="mt-3"><ProblemBox error={create.error} /></div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={create.isPending} disabled={missing || badLines.length > 0} onClick={() => create.mutate()}>Submit request</Button>
      </div>
    </Dialog>
  );
}
