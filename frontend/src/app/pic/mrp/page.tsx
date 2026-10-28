'use client';

import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';
import { Button, Card, DataTable, Field, Input, LinkButton, PageHeader, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, label, qty } from '@/lib/pic/format';
import { useApi, useCommand, useList } from '@/lib/pic/hooks';
import { PlannedOrder, PlannedOrderActions, SourceSummary, useMe } from './_components';

type Reference = { plants: { code: string; name: string }[] };
type Run = { id: string; number: string; mode: string; plant: string; run_date: string; status: string; materials_planned: number;
  planned_orders_created: number; exceptions_raised: number; created_at: string; completed_at: string | null };

const MODES = [
  { value: 'NET_CHANGE', label: 'Net change (materials with changed demand or supply)' },
  { value: 'REGENERATIVE', label: 'Regenerative (all MRP-planned materials)' },
  { value: 'SIMULATION', label: 'Simulation (no planned orders are saved)' },
];
const PO_STATUSES = ['', 'CREATED', 'FIRMED', 'CONVERTED', 'DELETED'];

export default function MrpConsole() {
  const { scopes } = useMe();
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="MRP-01 / MRP-02 / MRP-03 · Material requirements planning" title="MRP console"
        subtitle="Run net-change, regenerative or simulation planning per plant, review exceptions and firm or convert planned orders into purchase requisitions."
        actions={<LinkButton href="/pic/mrp/forecast">Demand forecast review (MRP-04)</LinkButton>} />
      <RunConsole canRun={scopes.includes('mrp:run')} />
      <Card title="MRP runs">
        <RunList />
      </Card>
      <PlannedOrders canPlan={scopes.includes('mrp:plan')} />
    </div>
  );
}

function RunConsole({ canRun }: { canRun: boolean }) {
  const router = useRouter();
  const ref = useApi<Reference>('/reference');
  const plants = ref.data?.plants ?? [];
  const [plant, setPlant] = useState('');
  const [mode, setMode] = useState('NET_CHANGE');
  const [runDate, setRunDate] = useState('');
  const [materials, setMaterials] = useState('');
  const effectivePlant = plant || plants[0]?.code || '';
  const start = useCommand(() => api.post<Run>('/mrp/runs', {
    plant: effectivePlant, mode,
    run_date: runDate || undefined,
    materials: materials.trim() ? materials.split(',').map((m) => m.trim()).filter(Boolean) : undefined,
  }), { success: (r) => `${r.number} completed: ${r.planned_orders_created} planned order(s), ${r.exceptions_raised} exception(s)`, onSuccess: (r) => router.push(`/pic/mrp/${r.number}`) });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!effectivePlant) return;
    start.mutate();
  };

  return (
    <Card title="Run console (MRP-01)">
      {ref.error && <ProblemBox error={ref.error} />}
      <form onSubmit={submit} className="grid gap-3 md:grid-cols-4 md:items-end">
        <Field label="Plant">{(id) => (
          <Select id={id} required value={effectivePlant} onChange={(e) => setPlant(e.target.value)}
            options={plants.length ? plants.map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` })) : [{ value: '', label: 'Loading plants…' }]} />
        )}</Field>
        <Field label="Run mode">{(id) => <Select id={id} value={mode} onChange={(e) => setMode(e.target.value)} options={MODES} />}</Field>
        <Field label="Run date (optional)" hint="Defaults to today">{(id) => <Input id={id} type="date" value={runDate} onChange={(e) => setRunDate(e.target.value)} />}</Field>
        <Field label="Materials (optional)" hint="Comma separated, e.g. DC-330, DC-331">{(id) => (
          <Input id={id} value={materials} onChange={(e) => setMaterials(e.target.value)} placeholder="All in scope" />
        )}</Field>
        <div className="flex flex-wrap items-center gap-3 md:col-span-4">
          <Button type="submit" variant="primary" busy={start.isPending} disabled={!canRun || !effectivePlant}>Start MRP run</Button>
          {!canRun && <p className="text-xs text-slate-500">Only an MRP controller can start a run.</p>}
          {mode === 'SIMULATION' ? <p className="text-xs text-amber-700">Simulation runs show the netting result only; no planned orders or exceptions are saved.</p> : <p className="text-xs text-slate-500">Unfirmed (created) planned orders from earlier runs are replaced by this run; firmed orders are kept.</p>}
        </div>
      </form>
    </Card>
  );
}

function RunList() {
  const list = useList<Run>('/mrp/runs');
  return (
    <DataTable<Run>
      rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
      loadingMore={list.isFetchingNextPage} rowHref={(r) => `/pic/mrp/${r.number}`} empty="No MRP runs yet"
      columns={[
        { key: 'number', header: 'Run' },
        { key: 'mode', header: 'Mode', render: (r) => label(r.mode) },
        { key: 'plant', header: 'Plant' },
        { key: 'run_date', header: 'Run date', render: (r) => date(r.run_date) },
        { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
        { key: 'materials_planned', header: 'Materials', align: 'right' },
        { key: 'planned_orders_created', header: 'Planned orders', align: 'right' },
        { key: 'exceptions_raised', header: 'Exceptions', align: 'right' },
        { key: 'completed_at', header: 'Completed', render: (r) => dateTime(r.completed_at) },
      ]}
    />
  );
}

function PlannedOrders({ canPlan }: { canPlan: boolean }) {
  const [status, setStatus] = useState('');
  const list = useList<PlannedOrder>(`/planned-orders${status ? `?status=${status}` : ''}`);
  return (
    <Card title="Planned orders (MRP-03)" actions={
      <Select aria-label="Filter planned orders by status" value={status} onChange={(e) => setStatus(e.target.value)}
        options={PO_STATUSES.map((s) => ({ value: s, label: s ? label(s) : 'All statuses' }))} />
    }>
      <DataTable<PlannedOrder>
        rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
        loadingMore={list.isFetchingNextPage} empty="No planned orders"
        columns={[
          { key: 'number', header: 'Planned order', render: (o) => <span className="font-medium">{o.number}</span> },
          { key: 'material', header: 'Material', render: (o) => o.material ?? '–' },
          { key: 'plant', header: 'Plant' },
          { key: 'qty', header: 'Quantity', align: 'right', render: (o) => qty(o.qty) },
          { key: 'release_date', header: 'Release', render: (o) => date(o.release_date) },
          { key: 'need_date', header: 'Need', render: (o) => date(o.need_date) },
          { key: 'source', header: 'Source determination', render: (o) => <SourceSummary source={o.source} /> },
          { key: 'exception_codes', header: 'Exceptions', render: (o) => o.exception_codes?.length ? o.exception_codes.map(label).join(', ') : '–' },
          { key: 'status', header: 'Status', render: (o) => <StatusChip status={o.status} /> },
          { key: 'actions', header: 'Actions', render: (o) => <PlannedOrderActions order={o} canPlan={canPlan} /> },
        ]}
      />
    </Card>
  );
}
