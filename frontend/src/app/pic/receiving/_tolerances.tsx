'use client';

import { useState } from 'react';
import { Button, DataTable, Field, Input, ProblemBox, Select } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { useApi, useCommand } from '@/lib/pic/hooks';
import type { Reference } from '../requisitions/_components';

type Tolerance = { id: string; material: string | null; supplier: string | null; overPct: string; underPct: string; reason: string; updatedAt: string };

/** BP M09 receipt tolerances per material and supplier. The most specific row (material + supplier, then supplier, then material)
 *  is copied to the order lines at PO creation and then limits over-delivery at ASN and goods receipt. */
export function ToleranceTab({ canManage }: { canManage: boolean }) {
  const list = useApi<Tolerance[]>('/receipt-tolerances');
  const ref = useApi<Reference>('/reference');
  const [material, setMaterial] = useState('');
  const [supplier, setSupplier] = useState('');
  const [over, setOver] = useState('');
  const [under, setUnder] = useState('');
  const [reason, setReason] = useState('');
  const save = useCommand(() => api.put<Tolerance>('/receipt-tolerances', {
    material: material || undefined, supplier: supplier || undefined, overPct: over, underPct: under, reason: reason.trim(),
  }), { success: 'Receipt tolerance saved', onSuccess: () => { setOver(''); setUnder(''); setReason(''); } });
  const remove = useCommand((id: string) => api.delete(`/receipt-tolerances/${id}`), { success: 'Receipt tolerance removed' });
  const valid = (material || supplier) && over !== '' && under !== '' && Number(over) >= 0 && Number(over) <= 100 && Number(under) >= 0 && Number(under) <= 100
    && reason.trim().length >= 3;
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        Over- and under-delivery tolerance for one material, one supplier, or the pair. It overrides the contract and the tenant default for
        orders created afterwards; the percentage in force is stored on each order line.
      </p>
      {list.error && <ProblemBox error={list.error} />}
      <DataTable<Tolerance> rows={list.data ?? []} loading={list.isLoading} empty="No overrides: the contract or the tenant default applies" columns={[
        { key: 'material', header: 'Material', render: (t) => t.material ?? 'any' },
        { key: 'supplier', header: 'Supplier', render: (t) => t.supplier ?? 'any' },
        { key: 'overPct', header: 'Over %', align: 'right' },
        { key: 'underPct', header: 'Under %', align: 'right' },
        { key: 'reason', header: 'Reason' },
        { key: 'action', header: '', render: (t) => canManage ? <Button variant="danger" busy={remove.isPending} onClick={() => remove.mutate(t.id)}>Remove</Button> : null },
      ]} />
      {canManage && (
        <div className="grid gap-3 md:grid-cols-6 md:items-end">
          <Field label="Material">{(id) => <Select id={id} value={material} onChange={(e) => setMaterial(e.target.value)}
            options={[{ value: '', label: 'Any material' }, ...(ref.data?.materials ?? []).map((m) => ({ value: m.number, label: `${m.number} · ${m.description}` }))]} />}</Field>
          <Field label="Supplier">{(id) => <Select id={id} value={supplier} onChange={(e) => setSupplier(e.target.value)}
            options={[{ value: '', label: 'Any supplier' }, ...(ref.data?.suppliers ?? []).map((s) => ({ value: s.code, label: `${s.code} · ${s.name}` }))]} />}</Field>
          <Field label="Over %">{(id) => <Input id={id} type="number" min="0" max="100" step="0.1" value={over} onChange={(e) => setOver(e.target.value)} />}</Field>
          <Field label="Under %">{(id) => <Input id={id} type="number" min="0" max="100" step="0.1" value={under} onChange={(e) => setUnder(e.target.value)} />}</Field>
          <Field label="Reason">{(id) => <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
          <Button variant="primary" busy={save.isPending} disabled={!valid} onClick={() => save.mutate()}>Save tolerance</Button>
        </div>
      )}
    </div>
  );
}
