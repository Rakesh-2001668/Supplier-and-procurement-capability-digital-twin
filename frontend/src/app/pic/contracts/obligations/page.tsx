'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Empty, Field, Kpi, LinkButton, Loading, PageHeader, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, inr } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { hasRole, useSessionUser } from '../../invoices/_components';

type Obligation = { id: string; contract: string; contractStatus: string; supplier: string | null; party: 'BUYER' | 'SUPPLIER'; description: string;
  dueDate: string; status: string; daysToDue: number };
type Tracker = { items: Obligation[]; overdue: number; dueSoon: number; completed: number };
type Renewal = { contract: string; title: string; supplier: string | null; status: string; validTo: string; noticeOn: string; daysToExpiry: number;
  expiringIn90: boolean; targetValueMinor: number };

// The tracker reports OPEN/DUE_SOON/OVERDUE for open obligations and the stored status otherwise (DONE once completed).
const isDone = (s: string) => s === 'DONE' || s === 'COMPLETED';
const STATE_STYLE: Record<string, string> = {
  OVERDUE: 'bg-red-50 text-red-800 ring-red-200',
  DUE_SOON: 'bg-amber-50 text-amber-800 ring-amber-200',
  OPEN: 'bg-blue-50 text-blue-800 ring-blue-200',
  DONE: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
};

function StateChip({ status }: { status: string }) {
  const key = isDone(status) ? 'DONE' : status;
  return (
    <span className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset ${STATE_STYLE[key] ?? STATE_STYLE.OPEN}`}>
      {isDone(status) ? 'Completed' : status.replace('_', ' ')}
    </span>
  );
}

const contractLink = (n: string) => <Link href={`/pic/contracts/${encodeURIComponent(n)}`} className="font-medium text-[#1A56DB] hover:underline">{n}</Link>;

export default function Obligations() {
  const user = useSessionUser();
  const canComplete = hasRole(user, 'CONTRACT_MANAGER');
  const [party, setParty] = useState('');
  const [state, setState] = useState('');
  const [completing, setCompleting] = useState<Obligation | null>(null);
  const tracker = useApi<Tracker>(`/obligations${party ? `?party=${party}` : ''}`);
  const items = (tracker.data?.items ?? []).filter((o) => !state || (state === 'DONE' ? isDone(o.status) : o.status === state));
  const completed = (tracker.data?.items ?? []).filter((o) => isDone(o.status)).length;

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="CLM-04 · Obligations & renewals" title="Obligation tracker"
        subtitle="Buyer and supplier obligations created from the contract playbook, with due dates, and the renewal calendar with each contract's notice date."
        actions={<>
          <LinkButton href="/pic/contracts">Contracts</LinkButton>
          <LinkButton href="/pic/contracts/new">New contract</LinkButton>
        </>} />

      {tracker.isLoading ? <Loading /> : tracker.error || !tracker.data ? <ProblemBox error={tracker.error} /> : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Overdue" value={tracker.data.overdue} tone={tracker.data.overdue ? 'bad' : 'good'} hint="past due date, not completed" />
            <Kpi label="Due in 30 days" value={tracker.data.dueSoon} tone={tracker.data.dueSoon ? 'warn' : 'default'} />
            <Kpi label="Completed" value={completed} tone={completed ? 'good' : 'default'} />
            <Kpi label="Tracked" value={tracker.data.items.length} hint={party ? `${party.toLowerCase()} obligations` : 'buyer and supplier'} />
          </div>

          <Card title="Obligations" actions={<>
            <Select aria-label="Filter by party" value={party} onChange={(e) => setParty(e.target.value)}
              options={[{ value: '', label: 'Both parties' }, { value: 'BUYER', label: 'Buyer (us)' }, { value: 'SUPPLIER', label: 'Supplier' }]} />
            <Select aria-label="Filter by status" value={state} onChange={(e) => setState(e.target.value)}
              options={[{ value: '', label: 'All statuses' }, { value: 'OVERDUE', label: 'Overdue' }, { value: 'DUE_SOON', label: 'Due soon' },
                { value: 'OPEN', label: 'Open' }, { value: 'DONE', label: 'Completed' }]} />
          </>}>
            <DataTable<Obligation> rows={items} empty="No obligations match" columns={[
              { key: 'status', header: 'Status', render: (o) => <StateChip status={o.status} /> },
              { key: 'description', header: 'Obligation', className: 'min-w-[220px]' },
              { key: 'party', header: 'Party', render: (o) => <StatusChip status={o.party} /> },
              { key: 'contract', header: 'Contract', render: (o) => <span>{contractLink(o.contract)}<span className="block text-xs text-slate-500">{o.contractStatus.replace(/_/g, ' ').toLowerCase()}</span></span> },
              { key: 'supplier', header: 'Supplier', render: (o) => o.supplier ?? '–' },
              { key: 'dueDate', header: 'Due', render: (o) => <span className="whitespace-nowrap">{date(o.dueDate)}</span> },
              { key: 'daysToDue', header: 'Days', align: 'right', render: (o) => isDone(o.status) ? '–' : (
                <span className={o.daysToDue < 0 ? 'font-semibold text-red-700' : o.daysToDue <= 30 ? 'text-amber-700' : ''}>
                  {o.daysToDue < 0 ? `${-o.daysToDue} late` : o.daysToDue}
                </span>
              ) },
              { key: 'action', header: '', render: (o) => !isDone(o.status) && canComplete ? <Button onClick={() => setCompleting(o)}>Mark complete</Button> : null },
            ]} />
          </Card>
        </>
      )}

      <RenewalCalendar />

      {completing && <CompleteDialog obligation={completing} onClose={() => setCompleting(null)} />}
    </div>
  );
}

function monthKey(d: string) {
  return d.slice(0, 7);
}

function RenewalCalendar() {
  const { data, isLoading, error } = useApi<Renewal[]>('/contracts-renewals');
  if (isLoading) return <Card title="Renewal calendar"><Loading /></Card>;
  if (error || !data) return <Card title="Renewal calendar"><ProblemBox error={error} /></Card>;
  if (!data.length) return <Card title="Renewal calendar"><Empty title="No active or pending contracts to renew" /></Card>;

  // Months from now to the furthest expiry (max 24), so the calendar reads left to right in time.
  const start = new Date();
  start.setDate(1);
  const last = data.reduce((m, r) => (r.validTo > m ? r.validTo : m), data[0].validTo);
  const months: string[] = [];
  for (let d = new Date(start); months.length < 24; d.setMonth(d.getMonth() + 1)) {
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    months.push(key);
    if (key >= monthKey(last)) break;
  }
  const monthName = (key: string) => new Intl.DateTimeFormat('en-IN', { month: 'short', year: 'numeric' }).format(new Date(`${key}-01T00:00:00`));
  const expiring90 = data.filter((r) => r.expiringIn90);

  return (
    <Card title="Renewal calendar" actions={expiring90.length ? <span className="text-sm font-semibold text-amber-700">{expiring90.length} expiring within 90 days</span> : undefined}>
      <p className="mb-3 text-sm text-slate-600">Each contract appears in its notice month (decide to renew or re-source) and its expiry month. Contracts expiring within 90 days are highlighted.</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
        {months.map((m) => {
          const notices = data.filter((r) => monthKey(r.noticeOn) === m);
          const expiries = data.filter((r) => monthKey(r.validTo) === m);
          const hot = expiries.some((r) => r.expiringIn90);
          return (
            <div key={m} className={`min-h-[84px] rounded-lg border p-2 ${hot ? 'border-amber-300 bg-amber-50' : notices.length || expiries.length ? 'border-slate-300 bg-white' : 'border-slate-100 bg-slate-50'}`}>
              <p className="text-xs font-semibold text-slate-600">{monthName(m)}</p>
              <ul className="mt-1 space-y-1 text-[11px] leading-tight">
                {notices.map((r) => <li key={`n-${r.contract}`} className="text-blue-800">Notice · {r.contract} ({date(r.noticeOn)})</li>)}
                {expiries.map((r) => <li key={`e-${r.contract}`} className={r.expiringIn90 ? 'font-semibold text-amber-900' : 'text-slate-800'}>Expires · {r.contract} ({date(r.validTo)})</li>)}
              </ul>
            </div>
          );
        })}
      </div>
      <div className="mt-4">
        <DataTable<Renewal> rows={data} columns={[
          { key: 'contract', header: 'Contract', render: (r) => contractLink(r.contract) },
          { key: 'title', header: 'Title', className: 'min-w-[220px]' },
          { key: 'supplier', header: 'Supplier', render: (r) => r.supplier ?? '–' },
          { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
          { key: 'noticeOn', header: 'Notice on', render: (r) => date(r.noticeOn) },
          { key: 'validTo', header: 'Expires', render: (r) => date(r.validTo) },
          { key: 'daysToExpiry', header: 'Days left', align: 'right', render: (r) => (
            <span className={r.expiringIn90 ? 'font-semibold text-amber-700' : r.daysToExpiry < 0 ? 'text-red-700' : ''}>{r.daysToExpiry}</span>
          ) },
          { key: 'targetValueMinor', header: 'Target value', align: 'right', render: (r) => inr(r.targetValueMinor) },
        ]} />
      </div>
    </Card>
  );
}

function CompleteDialog({ obligation, onClose }: { obligation: Obligation; onClose: () => void }) {
  const [note, setNote] = useState('');
  const cmd = useCommand(() => api.post(`/obligations/${obligation.id}/complete`, { note: note.trim() }), {
    success: 'Obligation marked complete', onSuccess: onClose,
  });
  return (
    <Dialog open title={`Complete: ${obligation.description}`} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-slate-700">{obligation.contract} · {obligation.party.toLowerCase()} obligation · due {date(obligation.dueDate)}</p>
        <Field label="Evidence note (required)" hint="Written to the contract's audit trail.">
          {(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. 13-week forecast shared by email on 6 Nov, ref FC-2026-45" />}
        </Field>
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={note.trim().length < 3} busy={cmd.isPending} onClick={() => cmd.mutate()}>Mark complete</Button>
        </div>
      </div>
    </Dialog>
  );
}
