'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, PageHeader, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { api, ApiError, Paged } from '@/lib/pic/api';
import { date, inr, label, qty, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Allocation = { qty: string; share: string | number | null; supplier: string; contractId: string | null; priceSource: string; unitPriceMinor: number | null };
type WorkItem = {
  requisition: string; line: number; origin: string; description: string; qty: string; uom: string; needDate: string; plant: string;
  sourcingStatus: string | null; source: { method?: string; allocations?: Allocation[]; excluded?: unknown[] } | null;
};
type Reference = { suppliers: { code: string; name: string; status: string }[] };
type Contract = { number: string; status: string; supplier_code: string; title: string | null; valid_to: string | null };
type Me = { scopes: string[] };
type PoResult = {
  id: string; version: number; status: string;
  inherited: { price: number | null; paymentTerms: string | null; incoterms: string | null; tolerance: string | null };
  validation: { riskScore: number | null; touchless: boolean | null; factors: { code: string; points: number; evidence: string }[] | null };
  lineage: string[];
};

const ORIGINS = ['', 'MRP', 'MANUAL', 'PROJECT', 'CATALOGUE'];

export default function BuyerWorkbench() {
  const [origin, setOrigin] = useState('');
  const queue = useApi<WorkItem[]>(`/buyer-workbench${origin ? `?origin=${origin}` : ''}`);
  const me = useApi<Me>('/me');
  const canOrder = !!me.data?.scopes.includes('po:create');
  const [selected, setSelected] = useState<WorkItem | null>(null);
  const rows = (queue.data ?? []).map((w) => ({ ...w, id: `${w.requisition}/${w.line}` }));

  return (
    <div>
      <PageHeader eyebrow="REQ-04 · Buyer workbench" title="Buyer workbench"
        subtitle="Approved requisition lines from MRP and manual demand waiting for a purchase order. Source determination runs contract → quota → source list → info record." />
      <Card title={`Open lines (${rows.length})`} actions={
        <Select aria-label="Filter by origin" value={origin} onChange={(e) => setOrigin(e.target.value)}
          options={ORIGINS.map((o) => ({ value: o, label: o ? label(o) : 'All origins' }))} />
      }>
        <DataTable<WorkItem & { id: string }>
          rows={rows} loading={queue.isLoading} error={queue.error} empty="No approved lines waiting for a PO"
          rowHref={(r) => `/pic/requisitions/${r.requisition}`}
          columns={[
            { key: 'requisition', header: 'Requisition', render: (r) => `${r.requisition} / ${r.line}` },
            { key: 'origin', header: 'Origin', render: (r) => label(r.origin) },
            { key: 'description', header: 'Item' },
            { key: 'qty', header: 'Open qty', align: 'right', render: (r) => qty(r.qty, r.uom) },
            { key: 'needDate', header: 'Need', render: (r) => date(r.needDate) },
            { key: 'plant', header: 'Plant' },
            { key: 'source', header: 'Source determination', render: (r) => <SourceCell source={r.source} /> },
            { key: 'sourcingStatus', header: 'Sourcing', render: (r) => r.sourcingStatus ? <StatusChip status={r.sourcingStatus} /> : '–' },
            { key: 'action', header: '', render: (r) => canOrder ? <Button variant="primary" onClick={() => setSelected(r)}>Create PO</Button> : null },
          ]}
        />
        {!canOrder && me.data && <p className="mt-3 text-xs text-slate-500">Only buyers can create purchase orders from this queue.</p>}
      </Card>
      {selected && <CreatePoDialog item={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function SourceCell({ source }: { source: WorkItem['source'] }) {
  if (!source?.method) return <span className="text-xs text-slate-500">Determined when the PO is created</span>;
  return (
    <div className="text-xs">
      <p className="font-semibold text-slate-800">{label(source.method)}</p>
      {(source.allocations ?? []).map((a, i) => (
        <p key={i} className="text-slate-600">
          {a.supplier} · {qty(a.qty)}{a.share ? ` (${a.share}%)` : ''}{a.unitPriceMinor != null ? ` @ ${inr(a.unitPriceMinor)}` : ''} · {label(a.priceSource)}
        </p>
      ))}
    </div>
  );
}

function CreatePoDialog({ item, onClose }: { item: WorkItem; onClose: () => void }) {
  const ref = useApi<Reference>('/reference');
  const contracts = useApi<Paged<Contract>>('/contracts?status=ACTIVE&limit=200');
  const [supplier, setSupplier] = useState('');
  const [contract, setContract] = useState('');
  const [releaseQty, setReleaseQty] = useState(item.qty);
  const [needDate, setNeedDate] = useState(item.needDate);
  const [price, setPrice] = useState('');
  const [reason, setReason] = useState('');
  const [result, setResult] = useState<PoResult[] | null>(null);

  const contractOptions = (contracts.data?.items ?? []).filter((c) => !supplier || c.supplier_code === supplier);
  const qtyNumber = Number(releaseQty);
  const invalid = !(qtyNumber > 0) || qtyNumber > Number(item.qty) || !needDate || (!!price && !(Number(price) > 0));

  const create = useCommand(() => api.post<PoResult | { purchaseOrders: PoResult[] }>('/purchase-orders', {
    source: { type: 'REQUISITION', id: item.requisition, lines: [item.line] },
    supplierId: supplier || undefined,
    contractRef: contract || undefined,
    release: { qty: releaseQty, needDate },
    unitPriceMinor: price ? rupeesToMinor(price) : undefined,
    deviationReason: reason.trim() || undefined,
  }), {
    success: (r) => 'purchaseOrders' in r ? `${r.purchaseOrders.length} purchase orders created` : `${r.id} created (${label(r.status)})`,
    onSuccess: (r) => setResult('purchaseOrders' in r ? r.purchaseOrders : [r]),
  });

  return (
    <Dialog open title={`Create PO from ${item.requisition} line ${item.line}`} onClose={onClose}>
      <div className="mb-4 rounded-lg bg-slate-50 p-3 text-sm">
        <p className="font-medium">{item.description}</p>
        <p className="text-slate-600">Open {qty(item.qty, item.uom)} · need {date(item.needDate)} · plant {item.plant} · {label(item.origin)}</p>
        <div className="mt-2"><SourceCell source={item.source} /></div>
      </div>

      {result ? <PoResults pos={result} onClose={onClose} /> : (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Supplier (optional)" hint="Leave empty for automatic source determination: contract → quota → source list → info record. Free-text lines need a supplier.">{(id) => (
              <Select id={id} value={supplier} onChange={(e) => { setSupplier(e.target.value); setContract(''); }}
                options={[{ value: '', label: 'Automatic source determination' },
                  ...(ref.data?.suppliers ?? []).map((s) => ({ value: s.code, label: `${s.code} · ${s.name}${s.status !== 'ACTIVE' ? ` (${label(s.status)})` : ''}` }))]} />
            )}</Field>
            <Field label="Contract (optional)" hint="Price and terms are then taken from the contract's valid price.">{(id) => (
              <Select id={id} value={contract} onChange={(e) => setContract(e.target.value)}
                options={[{ value: '', label: 'No contract reference' },
                  ...contractOptions.map((c) => ({ value: c.number, label: `${c.number} · ${c.supplier_code}${c.title ? ` · ${c.title}` : ''}` }))]} />
            )}</Field>
            <Field label={`Release quantity (${item.uom}) *`} hint={`Up to the open ${qty(item.qty)}`}>{(id) => (
              <Input id={id} type="number" min="0" step="any" max={item.qty} value={releaseQty} onChange={(e) => setReleaseQty(e.target.value)} />
            )}</Field>
            <Field label="Need date *">{(id) => <Input id={id} type="date" value={needDate} onChange={(e) => setNeedDate(e.target.value)} />}</Field>
            <Field label="Unit price override (₹, optional)" hint="Leave empty to inherit the price (P07)">{(id) => (
              <Input id={id} type="number" min="0" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} />
            )}</Field>
            <Field label="Deviation reason" hint="Required when the price deviates from the contract beyond tolerance">{(id) => (
              <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} disabled={!price} />
            )}</Field>
          </div>
          <div className="mt-3"><SourcingProblem error={create.error} /></div>
          <div className="mt-4 flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" busy={create.isPending} disabled={invalid} onClick={() => create.mutate()}>Create purchase order</Button>
          </div>
        </>
      )}
    </Dialog>
  );
}

function SourcingProblem({ error }: { error: ApiError | null }) {
  if (!error) return null;
  const excluded = error.problem?.excluded;
  return (
    <div className="space-y-1">
      <ProblemBox error={error} />
      {Array.isArray(excluded) && excluded.length > 0 && (
        <div className="text-xs text-slate-600">
          <p className="font-semibold">Excluded sources</p>
          <ul className="list-disc pl-5">{excluded.map((x, i) => <li key={i}>{typeof x === 'string' ? x : JSON.stringify(x)}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

function PoResults({ pos, onClose }: { pos: PoResult[]; onClose: () => void }) {
  return (
    <div className="space-y-3">
      {pos.map((po) => (
        <div key={po.id} className="rounded-lg border border-slate-200 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Link href={`/pic/purchase-orders/${po.id}`} className="font-semibold text-[#1A56DB] hover:underline">{po.id}</Link>
            <span className="text-xs text-slate-500">v{po.version}</span>
            <StatusChip status={po.status} />
          </div>
          <p className="mt-1 text-sm">
            Risk score <span className="font-semibold">{po.validation.riskScore ?? '–'}/100</span> ·{' '}
            {po.validation.touchless ? <span className="text-emerald-700">touchless release (DMN-02)</span> : <span className="text-amber-700">routed for approval</span>}
          </p>
          {po.validation.factors?.length ? (
            <ul className="text-xs text-slate-600">{po.validation.factors.map((f) => <li key={f.code}>+{f.points} {label(f.code).toLowerCase()} — {f.evidence}</li>)}</ul>
          ) : null}
          <p className="mt-1 text-xs text-slate-600">
            Inherited: price {po.inherited.price != null ? `₹${po.inherited.price.toLocaleString('en-IN')}` : '–'} · terms {po.inherited.paymentTerms ?? '–'} · incoterms {po.inherited.incoterms ?? '–'} · tolerance {po.inherited.tolerance ?? '–'}
          </p>
          <p className="text-xs text-slate-500">Lineage: {po.lineage.length ? po.lineage.join(' → ') : '–'} → {po.id}</p>
        </div>
      ))}
      <div className="flex justify-end"><Button variant="primary" onClick={onClose}>Done</Button></div>
    </div>
  );
}
