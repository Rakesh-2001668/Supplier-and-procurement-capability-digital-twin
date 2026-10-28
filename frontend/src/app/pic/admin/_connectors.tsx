'use client';

import { FormEvent, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Card, DataTable, Field, Input, Loading, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { ApiError } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand, useList } from '@/lib/pic/hooks';
import { api } from '@/lib/pic/api';

type ConfigItem = { name: string; present: boolean; required: boolean; secret: boolean };
type Connector = {
  system: string; name: string; protocol: string; simulator: boolean; messageTypes: string[]; configuration: ConfigItem[]; configured: boolean;
  missing: string[]; healthy: boolean | null; lastCheck: { healthy: boolean; detail: string; checkedAt: string } | null;
  messages: Record<string, number>; total: number;
};
type HealthResult = { system: string; configured: boolean; healthy: boolean; detail: string; checkedAt: string };
type RowResult = { row: number; externalRef: string | null; status: string; error?: string; plannedOrder?: string; mrpRun?: string };
type Batch = { id: string; number: string; sourceSystem: string; kind: string; batchRef: string; rows: number; accepted: number; rejected: number;
  mrpRuns: string[]; results: RowResult[]; createdAt: string; replayed?: boolean };

function health(c: Connector) {
  if (c.simulator) return 'SIMULATED';
  if (!c.configured) return 'NOT_CONFIGURED';
  if (c.healthy === null) return 'NOT_TESTED';
  return c.healthy ? 'OK' : 'FAILED';
}

function ConnectorCard({ c }: { c: Connector }) {
  const [result, setResult] = useState<HealthResult | null>(null);
  const test = useCommand(() => api.post<HealthResult>(`/admin/connectors/${c.system}/test`, {}, { idempotencyKey: false }), {
    onSuccess: setResult,
  });
  const last = result ?? c.lastCheck;
  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium text-slate-900">{c.name} <span className="font-mono text-xs text-slate-500">{c.system}</span></p>
          <p className="text-xs text-slate-500">{c.protocol}</p>
        </div>
        <div className="flex items-center gap-2">
          <StatusChip status={health(c)} />
          <Button onClick={() => test.mutate()} busy={test.isPending}>Test connection</Button>
        </div>
      </div>
      <p className="mt-2 text-xs text-slate-600">Messages: {c.messageTypes.map((m) => label(m)).join(', ')}</p>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        {Object.keys(c.messages).length ? Object.entries(c.messages).map(([status, n]) => (
          <span key={status} className="inline-flex items-center gap-1"><StatusChip status={status} /><span className="tabular-nums">{n}</span></span>
        )) : <span className="text-slate-500">No messages sent to this system</span>}
      </div>
      {!c.simulator && (
        <ul className="mt-3 grid gap-1 text-xs sm:grid-cols-2">
          {c.configuration.map((item) => (
            <li key={item.name} className="flex items-center gap-1.5">
              <span aria-hidden className={`h-2 w-2 rounded-full ${item.present ? 'bg-emerald-500' : item.required ? 'bg-red-400' : 'bg-slate-300'}`} />
              <span className="font-mono">{item.name}</span>
              <span className="text-slate-500">{item.present ? 'set' : item.required ? 'missing' : 'optional'}{item.secret ? ' · secret' : ''}</span>
            </li>
          ))}
        </ul>
      )}
      {last && (
        <p className={`mt-2 text-xs ${last.healthy ? 'text-emerald-700' : 'text-red-700'}`}>
          Last check {dateTime(last.checkedAt)}: {last.detail}
        </p>
      )}
    </div>
  );
}

function ImportPanel() {
  const client = useQueryClient();
  const [system, setSystem] = useState('SAP_S4');
  const [batchRef, setBatchRef] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<Batch | null>(null);
  const batches = useList<Batch>('/integration/batches?kind=PLANNED_ORDERS');

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/pic/v1/integration/planned-orders/import/csv?system=${encodeURIComponent(system)}&batchRef=${encodeURIComponent(batchRef.trim())}`, {
        method: 'POST', headers: { 'content-type': 'text/csv', accept: 'application/json' }, body: await file.text(),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new ApiError({ status: response.status, code: data?.code ?? 'ERROR', ...data });
      setResult(data as Batch);
      await client.invalidateQueries();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="ERP planned-order import (AD-05)">
      <p className="mb-3 text-sm text-slate-600">
        Planned orders calculated by the ERP&apos;s MRP become platform planned orders on an MRP run with mode ERP import, so firming and
        conversion to requisitions work as for platform runs. CSV header: <span className="font-mono text-xs">externalRef, material, plant, qty,
        needDate</span> and optionally <span className="font-mono text-xs">releaseDate, supplier, storageLocation</span>. Resending a batch
        reference returns the original result. ERPs can also post JSON to <span className="font-mono text-xs">POST /v1/integration/planned-orders/import</span>.
      </p>
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-4 sm:items-end">
        <Field label="Source system">{(id) => (
          <Select id={id} value={system} onChange={(e) => setSystem(e.target.value)}
            options={['SAP_S4', 'ORACLE_FUSION', 'DYNAMICS_365', 'TALLY_PRIME', 'ODOO'].map((v) => ({ value: v, label: label(v) }))} />
        )}</Field>
        <Field label="Batch reference (required)">{(id) => <Input id={id} required maxLength={80} value={batchRef} onChange={(e) => setBatchRef(e.target.value)} placeholder="e.g. MD01-2026-10-28" />}</Field>
        <Field label="CSV file (required)">{(id) => <Input id={id} type="file" accept=".csv,text/csv" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} />}</Field>
        <Button type="submit" variant="primary" busy={busy} disabled={!file || !batchRef.trim()}>Import</Button>
      </form>
      <div className="mt-3"><ProblemBox error={error} /></div>
      {result && (
        <div className="mt-3 rounded-lg border border-slate-200 p-3 text-sm">
          <p className="font-medium">{result.number}{result.replayed ? ' (already imported — original result)' : ''}: {result.accepted} accepted, {result.rejected} rejected
            {result.mrpRuns.length ? ` · MRP run ${result.mrpRuns.join(', ')}` : ''}</p>
          {result.results.filter((r) => r.status === 'REJECTED').length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-xs text-red-800">
              {result.results.filter((r) => r.status === 'REJECTED').map((r) => <li key={r.row}>Row {r.row} {r.externalRef ?? ''}: {r.error}</li>)}
            </ul>
          )}
        </div>
      )}
      <div className="mt-4">
        <DataTable<Batch> loading={batches.isLoading} error={batches.error} rows={batches.items} empty="No ERP batches imported yet"
          onLoadMore={() => batches.fetchNextPage()} hasMore={batches.hasNextPage} loadingMore={batches.isFetchingNextPage}
          columns={[
            { key: 'number', header: 'Batch' },
            { key: 'sourceSystem', header: 'System', render: (b) => label(b.sourceSystem) },
            { key: 'batchRef', header: 'ERP reference', render: (b) => <span className="font-mono text-xs">{b.batchRef}</span> },
            { key: 'rows', header: 'Rows', align: 'right' },
            { key: 'accepted', header: 'Accepted', align: 'right' },
            { key: 'rejected', header: 'Rejected', align: 'right' },
            { key: 'mrpRuns', header: 'MRP runs', render: (b) => b.mrpRuns.length ? b.mrpRuns.map((r) => (
              <a key={r} href={`/pic/mrp/${encodeURIComponent(r)}`} className="mr-2 text-[#1A56DB] hover:underline">{r}</a>)) : '–' },
            { key: 'createdAt', header: 'Imported', render: (b) => dateTime(b.createdAt) },
          ]} />
      </div>
    </Card>
  );
}

export function ConnectorsTab() {
  const data = useApi<{ defaultTarget: string; connectors: Connector[] }>('/admin/connectors');
  return (
    <div className="space-y-4">
      <Card title="ERP connectors (TD §12.1)">
        <p className="mb-3 text-sm text-slate-600">
          Outbound postings (supplier invoices, purchase orders, goods receipts, masters, payments) run exactly once through the integration
          outbox. Unconfigured or failing connectors retry with back-off and dead-letter after 8 attempts (see the integration monitor).
          Configuration comes from environment variables on the API server; secrets are never shown. Default target: {data.data?.defaultTarget ?? '…'}.
        </p>
        {data.isLoading ? <Loading /> : data.error ? <ProblemBox error={data.error} /> : (
          <div className="grid gap-3 lg:grid-cols-2">{data.data?.connectors.map((c) => <ConnectorCard key={c.system} c={c} />)}</div>
        )}
      </Card>
      <ImportPanel />
    </div>
  );
}
