'use client';

import { FormEvent, useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Job = { key: string; name: string; description: string; registered: boolean; schedule: string; defaultSchedule: string | null; enabled: boolean;
  nextRunAt: string | null; lastRunAt: string | null; lastStatus: string | null; lastDurationMs: number | null; lastError: string | null; runCount: number;
  consecutiveFailures: number; running: boolean; overdue: boolean; supportsDryRun: boolean; version: number };
type Run = { id: string; job: string; trigger: string; dryRun: boolean; status: string; startedAt: string; finishedAt: string | null; durationMs: number | null;
  result: unknown; error: string | null; triggeredBy: string | null };

function Json({ value }: { value: unknown }) {
  return <pre className="max-h-64 max-w-xl overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-[11px] text-slate-800">{JSON.stringify(value, null, 1)}</pre>;
}

function HistoryDialog({ job, onClose }: { job: Job; onClose: () => void }) {
  const { data, isLoading, error } = useApi<Run[]>(`/admin/jobs/${job.key}/runs?limit=50`);
  return (
    <Dialog open title={`Run history · ${job.name}`} onClose={onClose}>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : (
        <DataTable<Run> rows={data ?? []} empty="This job has not run yet" columns={[
          { key: 'startedAt', header: 'Started', render: (r) => <span className="whitespace-nowrap text-xs">{dateTime(r.startedAt)}</span> },
          { key: 'trigger', header: 'Trigger', render: (r) => <span className="text-xs">{label(r.trigger)}{r.dryRun ? ' (dry run)' : ''}</span> },
          { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
          { key: 'durationMs', header: 'ms', align: 'right', render: (r) => r.durationMs ?? '–' },
          { key: 'result', header: 'Result', render: (r) => (r.error ? <span className="text-xs text-red-800">{r.error}</span> : (
            <details><summary className="cursor-pointer text-xs font-medium text-[#1A56DB]">Show</summary><Json value={r.result} /></details>)) },
        ]} />
      )}
    </Dialog>
  );
}

function ScheduleDialog({ job, onClose }: { job: Job; onClose: () => void }) {
  const [schedule, setSchedule] = useState(job.schedule);
  const cmd = useCommand((body: { schedule: string; reason: string }) => api.put<Job>(`/admin/jobs/${job.key}`, body, { ifMatch: String(job.version) }), {
    success: `${job.name}: schedule changed`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`Schedule · ${job.name}`} onClose={onClose}>
      <form onSubmit={(e: FormEvent) => { e.preventDefault(); cmd.mutate({ schedule: schedule.trim(), reason: 'Changed in the administration screen' }); }} className="space-y-3">
        <p className="text-sm text-slate-700">Five fields in your organisation&apos;s time zone: minute, hour, day of month, month, day of week
          (for example <span className="font-mono">30 6 * * *</span> is every day at 06:30), or <span className="font-mono">@daily</span>, <span className="font-mono">@hourly</span>,
          <span className="font-mono"> @weekly</span>, <span className="font-mono">@monthly</span>. Default: <span className="font-mono">{job.defaultSchedule ?? '–'}</span>.</p>
        <Field label="Schedule">{(id) => <Input id={id} required value={schedule} onChange={(e) => setSchedule(e.target.value)} className="font-mono" />}</Field>
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={cmd.isPending}>Save schedule</Button>
        </div>
      </form>
    </Dialog>
  );
}

function ArchiveCard() {
  const batches = useApi<{ batches: { id: string; seqFrom: number; seqTo: number; events: number; headHash: string; from: string; to: string; status: string }[];
    verification: { valid: boolean; checked: number } }>('/admin/audit/archive');
  const [result, setResult] = useState<unknown>(null);
  const archive = useCommand(() => api.post('/admin/audit/archive', { dryRun: true }), { onSuccess: setResult, success: 'Archive dry run finished' });
  const purge = useCommand(() => api.post('/admin/privacy/retention/purge', { dryRun: true }), { onSuccess: setResult, success: 'Retention dry run finished' });
  return (
    <Card title="Audit archive and data retention"
      actions={<div className="flex gap-2"><Button onClick={() => archive.mutate()} busy={archive.isPending}>Dry-run audit archive</Button>
        <Button onClick={() => purge.mutate()} busy={purge.isPending}>Dry-run retention purge</Button></div>}>
      <p className="mb-3 text-sm text-slate-600">Old audit events move to a verified archive; the hash chain is checked across it. The purge and archive jobs only
        report until rule PRIVACY-RETENTION sets <span className="font-mono">purge.dryRun</span> to false.</p>
      {batches.isLoading ? <Loading /> : batches.error ? <ProblemBox error={batches.error} /> : batches.data && (
        <>
          <p className="mb-2 text-sm">Chain verification: <StatusChip status={batches.data.verification.valid ? 'VALID' : 'BROKEN'} /> <span className="text-xs text-slate-500">
            {batches.data.verification.checked} events checked, {batches.data.batches.length} archived batch(es)</span></p>
          {batches.data.batches.length > 0 && (
            <DataTable rows={batches.data.batches as unknown as Record<string, unknown>[]} columns={[
              { key: 'seq', header: 'Sequence', render: (r) => `${r.seqFrom}–${r.seqTo}` },
              { key: 'events', header: 'Events', align: 'right' },
              { key: 'range', header: 'Period', render: (r) => `${date(r.from as string)} → ${date(r.to as string)}` },
              { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status as string} /> },
              { key: 'headHash', header: 'Checkpoint', render: (r) => <span className="font-mono text-[11px]">{String(r.headHash).slice(0, 16)}…</span> },
            ]} />
          )}
        </>
      )}
      {result !== null && <div className="mt-3"><Json value={result} /></div>}
      <ProblemBox error={archive.error ?? purge.error} />
    </Card>
  );
}

export function JobsTab() {
  const { data, isLoading, error } = useApi<Job[]>('/admin/jobs', { refetchInterval: 15000 });
  const [history, setHistory] = useState<Job | null>(null);
  const [editing, setEditing] = useState<Job | null>(null);
  const [lastRun, setLastRun] = useState<Run | null>(null);
  const run = useCommand((a: { key: string; dryRun: boolean }) => api.post<Run>(`/admin/jobs/${a.key}/run`, { dryRun: a.dryRun }), {
    success: (r) => `${r.job}: ${r.status.toLowerCase()}${r.dryRun ? ' (dry run)' : ''}`, onSuccess: setLastRun,
  });
  const toggle = useCommand((j: Job) => api.put<Job>(`/admin/jobs/${j.key}`, { enabled: !j.enabled, reason: j.enabled ? 'Switched off in the administration screen' : 'Switched on in the administration screen' },
    { ifMatch: String(j.version) }), { success: (j) => `${j.name}: ${j.enabled ? 'switched on' : 'switched off'}` });
  return (
    <div className="space-y-4">
      <Card title="Scheduled jobs">
        <p className="mb-3 text-sm text-slate-600">Jobs run on the worker, or from the scheduler call every minute on serverless hosting. Each job runs one at a time
          per organisation; a failure is recorded here and never stops the other jobs.</p>
        {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : (
          <DataTable<Job & Record<string, unknown>> rows={(data ?? []) as (Job & Record<string, unknown>)[]} empty="No jobs registered" columns={[
            { key: 'name', header: 'Job', className: 'min-w-[220px]', render: (j) => (
              <div><p className="font-medium text-slate-900">{j.name} <span className="font-mono text-[11px] text-slate-500">{j.key}</span></p>
                <p className="mt-0.5 max-w-md text-xs text-slate-600">{j.description}</p></div>) },
            { key: 'schedule', header: 'Schedule', render: (j) => <span className="font-mono text-xs">{j.schedule}</span> },
            { key: 'enabled', header: 'State', render: (j) => <StatusChip status={j.running ? 'RUNNING' : j.enabled ? 'ENABLED' : 'DISABLED'} /> },
            { key: 'nextRunAt', header: 'Next run', render: (j) => <span className="whitespace-nowrap text-xs">{j.enabled ? dateTime(j.nextRunAt) : '–'}{j.overdue ? ' (overdue)' : ''}</span> },
            { key: 'lastRunAt', header: 'Last run', render: (j) => (
              <div className="text-xs"><span className="whitespace-nowrap">{dateTime(j.lastRunAt)}</span><br />
                {j.lastStatus ? <StatusChip status={j.lastStatus} /> : '–'} {j.lastDurationMs !== null ? `${j.lastDurationMs} ms` : ''}
                {j.lastError && <p className="mt-1 max-w-xs text-red-800">{j.lastError}</p>}
                {j.consecutiveFailures > 0 && <p className="text-red-800">{j.consecutiveFailures} failure(s) in a row</p>}</div>) },
            { key: 'actions', header: 'Actions', render: (j) => (
              <div className="flex flex-wrap gap-1">
                <Button onClick={() => run.mutate({ key: j.key, dryRun: false })} busy={run.isPending} disabled={j.running}>Run now</Button>
                {j.supportsDryRun && <Button onClick={() => run.mutate({ key: j.key, dryRun: true })} busy={run.isPending} disabled={j.running}>Dry run</Button>}
                <Button onClick={() => toggle.mutate(j)} busy={toggle.isPending}>{j.enabled ? 'Disable' : 'Enable'}</Button>
                <Button onClick={() => setEditing(j)}>Schedule</Button>
                <Button onClick={() => setHistory(j)}>History</Button>
              </div>) },
          ]} />
        )}
        <ProblemBox error={run.error ?? toggle.error} />
        {lastRun && <div className="mt-3"><p className="mb-1 text-xs font-medium text-slate-700">Last manual run: {lastRun.job} · {lastRun.status}{lastRun.dryRun ? ' (dry run)' : ''}</p>
          {lastRun.error ? <p className="text-sm text-red-800">{lastRun.error}</p> : <Json value={lastRun.result} />}</div>}
      </Card>
      <ArchiveCard />
      {history && <HistoryDialog job={history} onClose={() => setHistory(null)} />}
      {editing && <ScheduleDialog job={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------- delegation overview (admin)
type Delegation = { id: string; delegator: string; delegatorEmail: string; delegate: string; delegateEmail: string; validFrom: string; validTo: string;
  roles: string[]; valueLimitMinor: number | null; reason: string; status: string; version: number; delegatorId: string };

function RevokeDialog({ item, onClose }: { item: Delegation; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const cmd = useCommand(() => api.post(`/admin/delegations/${item.id}/revoke`, { reason: reason.trim() }, { ifMatch: String(item.version) }), {
    success: 'Delegation revoked', onSuccess: onClose,
  });
  return (
    <Dialog open title={`Revoke delegation · ${item.delegator} → ${item.delegate}`} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2"><Button onClick={onClose}>Cancel</Button>
          <Button variant="danger" disabled={reason.trim().length < 3} busy={cmd.isPending} onClick={() => cmd.mutate()}>Revoke</Button></div>
      </div>
    </Dialog>
  );
}

export function DelegationsTab() {
  const [status, setStatus] = useState('');
  const { data, isLoading, error } = useApi<Delegation[]>(`/admin/delegations${status ? `?status=${status}` : ''}`);
  const [revoking, setRevoking] = useState<Delegation | null>(null);
  return (
    <Card title="Delegations of authority"
      actions={<Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}
        options={[{ value: '', label: 'All' }, ...['ACTIVE', 'SCHEDULED', 'EXPIRED', 'REVOKED'].map((s) => ({ value: s, label: label(s) }))]} />}>
      <p className="mb-3 text-sm text-slate-600">While a delegation is in force the delegate can decide the delegator&apos;s approval tasks; each decision is recorded as made on behalf
        of the delegator, and four-eyes is checked for both people. Users create their own under My account.</p>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : (
        <DataTable<Delegation & Record<string, unknown>> rows={(data ?? []) as (Delegation & Record<string, unknown>)[]} empty="No delegations" columns={[
          { key: 'delegator', header: 'Delegator', render: (d) => <span>{d.delegator}<br /><span className="text-xs text-slate-500">{d.delegatorEmail}</span></span> },
          { key: 'delegate', header: 'Delegate', render: (d) => <span>{d.delegate}<br /><span className="text-xs text-slate-500">{d.delegateEmail}</span></span> },
          { key: 'period', header: 'Period', render: (d) => <span className="whitespace-nowrap text-xs">{date(d.validFrom)} → {date(d.validTo)}</span> },
          { key: 'scope', header: 'Scope', render: (d) => <span className="text-xs">{d.roles.length ? d.roles.map((r) => label(r)).join(', ') : 'All roles'}{d.valueLimitMinor ? ` · up to ₹${(d.valueLimitMinor / 100).toLocaleString('en-IN')}` : ''}</span> },
          { key: 'reason', header: 'Reason', render: (d) => <span className="text-xs">{d.reason}</span> },
          { key: 'status', header: 'Status', render: (d) => <StatusChip status={d.status} /> },
          { key: 'actions', header: '', render: (d) => (d.status === 'ACTIVE' || d.status === 'SCHEDULED') ? <Button variant="danger" onClick={() => setRevoking(d)}>Revoke</Button> : null },
        ]} />
      )}
      {revoking && <RevokeDialog item={revoking} onClose={() => setRevoking(null)} />}
    </Card>
  );
}
