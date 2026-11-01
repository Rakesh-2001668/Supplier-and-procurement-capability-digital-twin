'use client';

import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Loading, ProblemBox, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Reject = { object: string; key: string; reason: string; detail: string };
type SyncRun = { id: string; number: string; system: string; kind: string; label: string; mode: string; source: string; status: string; startedAt: string;
  finishedAt: string | null; cursorBefore: string | null; cursorAfter: string | null; attempts: number; counts: Record<string, number>; rejects: Reject[];
  error: string | null; triggeredBy: string | null; replayed?: boolean };
type KindRow = { kind: string; label: string; system: string; cursor: string | null; lastStatus: string | null; lastRunAt: string | null;
  consecutiveFailures: number; lastRun: SyncRun | null };
type Overview = { defaultSystem: string; kinds: KindRow[]; recentRuns: SyncRun[];
  sources: { connector: { system: string; configured: boolean; simulator: boolean; detail: string }; fileDrop: { directory: string | null; configured: boolean };
    sftp: { configured: boolean } } };

function csv(rows: Reject[]): string {
  const cell = (v: string) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  return ['object,key,reason,detail', ...rows.map((r) => [r.object, r.key, r.reason, r.detail].map(cell).join(','))].join('\n');
}

function RunDialog({ run, onClose }: { run: SyncRun; onClose: () => void }) {
  function download() {
    const url = URL.createObjectURL(new Blob([csv(run.rejects)], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${run.number}-rejects.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <Dialog open title={`${run.number} · ${run.label}`} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-slate-700">
          <StatusChip status={run.status} /> {label(run.mode)} run from {label(run.source)} on {label(run.system)}, started {dateTime(run.startedAt)}
          {run.finishedAt ? `, finished ${dateTime(run.finishedAt)}` : ''}. Cursor {run.cursorBefore ?? 'none'} → {run.cursorAfter ?? 'unchanged'}; attempts {run.attempts}.
        </p>
        <dl className="grid grid-cols-3 gap-2 text-xs sm:grid-cols-6">
          {Object.entries(run.counts).map(([k, v]) => (
            <div key={k} className="rounded-lg border border-slate-200 px-2 py-1"><dt className="text-slate-500">{label(k)}</dt><dd className="text-base font-semibold tabular-nums">{v}</dd></div>
          ))}
        </dl>
        {run.error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">{run.error}</p>}
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">Rejects and exceptions ({run.rejects.length})</p>
          {run.rejects.length > 0 && <Button onClick={download}>Download CSV</Button>}
        </div>
        <DataTable<Reject & { id: string }> rows={run.rejects.map((r, i) => ({ ...r, id: `${i}` }))} empty="Nothing was rejected and no differences were found" columns={[
          { key: 'object', header: 'Object', render: (r) => <span className="text-xs">{label(r.object)}</span> },
          { key: 'key', header: 'Key', render: (r) => <span className="font-mono text-xs">{r.key}</span> },
          { key: 'reason', header: 'Reason', render: (r) => <span className="font-mono text-xs">{r.reason}</span> },
          { key: 'detail', header: 'Detail', className: 'min-w-[260px]', render: (r) => <span className="text-xs">{r.detail}</span> },
        ]} />
      </div>
    </Dialog>
  );
}

export function ErpSyncTab() {
  const { data, isLoading, error } = useApi<Overview>('/admin/erp-sync');
  const [open, setOpen] = useState<SyncRun | null>(null);
  const run = useCommand((kind: string) => api.post<SyncRun>(`/admin/erp-sync/${kind}/run`, {}), {
    onSuccess: (r) => setOpen(r),
    success: 'Sync finished',
  });
  const retry = useCommand(() => api.post<{ runs: SyncRun[] }>('/admin/erp-sync/retry-failed', {}), { success: 'Failed syncs run again' });
  const failed = data?.kinds.filter((k) => k.lastStatus === 'FAILED').length ?? 0;
  return (
    <div className="space-y-4">
      <Card title="ERP inbound sync (TD §12.1)"
        actions={failed > 0 ? <Button onClick={() => retry.mutate()} busy={retry.isPending}>Retry {failed} failed</Button> : undefined}>
        <p className="mb-3 text-sm text-slate-600">
          Masters (plants, cost objects, vendors, materials), stock levels, open purchase orders, payment status and planned orders are pulled from the ERP
          connector on a schedule (see Jobs) or on demand here. Each object kind keeps its own delta cursor; only changed objects are applied. Bank and
          tax-ID differences on existing vendors are never applied: they become MDM-04 change requests. Rejected rows and differences are listed per run.
        </p>
        {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : data && (
          <>
            <ul className="mb-3 grid gap-1 text-xs sm:grid-cols-3">
              <li><span className={`mr-1.5 inline-block h-2 w-2 rounded-full ${data.sources.connector.configured ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                Connector {label(data.sources.connector.system)}: {data.sources.connector.detail}</li>
              <li><span className={`mr-1.5 inline-block h-2 w-2 rounded-full ${data.sources.fileDrop.configured ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                File drop: {data.sources.fileDrop.directory ?? 'PIC_ERP_SYNC_DROP_DIR not set'}</li>
              <li><span className={`mr-1.5 inline-block h-2 w-2 rounded-full ${data.sources.sftp.configured ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                SFTP: {data.sources.sftp.configured ? 'configured' : 'PIC_ERP_SYNC_SFTP_HOST not set'}</li>
            </ul>
            <DataTable<KindRow & { id: string }> rows={data.kinds.map((k) => ({ ...k, id: `${k.system}-${k.kind}` }))} empty="No object kinds" columns={[
              { key: 'label', header: 'Object', render: (k) => <span className="font-medium">{k.label}</span> },
              { key: 'system', header: 'System', render: (k) => label(k.system) },
              { key: 'lastStatus', header: 'Last run', render: (k) => k.lastStatus ? <StatusChip status={k.lastStatus} /> : <span className="text-slate-400">never</span> },
              { key: 'lastRunAt', header: 'When', render: (k) => k.lastRunAt ? <span className="whitespace-nowrap text-xs">{dateTime(k.lastRunAt)}</span> : '–' },
              { key: 'counts', header: 'Result', render: (k) => k.lastRun ? (
                <span className="text-xs">{Object.entries(k.lastRun.counts).filter(([, v]) => v).map(([c, v]) => `${v} ${c}`).join(' · ') || 'no change'}</span>) : '–' },
              { key: 'cursor', header: 'Cursor', render: (k) => <span className="font-mono text-xs">{k.cursor ?? '–'}</span> },
              { key: 'consecutiveFailures', header: 'Failures', align: 'right', render: (k) => k.consecutiveFailures || '–' },
              { key: 'action', header: '', render: (k) => (
                <div className="flex gap-2">
                  <Button variant="primary" busy={run.isPending && run.variables === k.kind} disabled={run.isPending}
                    onClick={() => run.mutate(k.kind)}>Run now</Button>
                  {k.lastRun && <Button onClick={() => setOpen(k.lastRun)}>Last report</Button>}
                </div>) },
            ]} />
            <div className="mt-2"><ProblemBox error={run.error} /></div>
          </>
        )}
      </Card>
      <Card title="Recent runs">
        <DataTable<SyncRun> rows={data?.recentRuns ?? []} loading={isLoading} empty="No sync has run yet" columns={[
          { key: 'number', header: 'Run', render: (r) => <button type="button" className="font-mono text-xs text-[#1A56DB] hover:underline" onClick={() => setOpen(r)}>{r.number}</button> },
          { key: 'label', header: 'Object' },
          { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
          { key: 'source', header: 'Source', render: (r) => <span className="text-xs">{label(r.source)} · {label(r.mode)}</span> },
          { key: 'startedAt', header: 'Started', render: (r) => <span className="whitespace-nowrap text-xs">{dateTime(r.startedAt)}</span> },
          { key: 'rejects', header: 'Rejects / exceptions', align: 'right', render: (r) => r.rejects.length || '–' },
        ]} />
      </Card>
      {open && <RunDialog run={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
