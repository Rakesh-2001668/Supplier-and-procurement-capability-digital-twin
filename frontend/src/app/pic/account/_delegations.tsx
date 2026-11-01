'use client';

import { FormEvent, useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Delegation = { id: string; delegator: string; delegatorEmail: string; delegate: string; delegateEmail: string; validFrom: string; validTo: string;
  roles: string[]; valueLimitMinor: number | null; reason: string; status: string; version: number; revokeReason: string | null;
  blockedTasks?: { ref: string; reason: string }[] };
type Mine = { given: Delegation[]; received: Delegation[] };
type Candidate = { id: string; name: string; email: string; roles: string[] };

function today() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());
}

function NewDelegationDialog({ roles, onClose }: { roles: string[]; onClose: () => void }) {
  const candidates = useApi<Candidate[]>('/me/delegation-candidates');
  const [f, setF] = useState({ delegateId: '', validFrom: today(), validTo: today(), role: '', limit: '', reason: '' });
  const [blocked, setBlocked] = useState<{ ref: string; reason: string }[]>([]);
  const cmd = useCommand((body: Record<string, unknown>) => api.post<Delegation>('/me/delegations', body), {
    success: 'Delegation set', onSuccess: (d) => { if (d.blockedTasks?.length) setBlocked(d.blockedTasks); else onClose(); },
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));
  function submit(e: FormEvent) {
    e.preventDefault();
    const limit = f.limit.trim() ? Math.round(Number(f.limit) * 100) : undefined;
    cmd.mutate({ delegateId: f.delegateId, validFrom: f.validFrom, validTo: f.validTo, roles: f.role ? [f.role] : [], valueLimitMinor: limit, reason: f.reason.trim() });
  }
  if (blocked.length) {
    return (
      <Dialog open title="Delegation set" onClose={onClose}>
        <div className="space-y-3 text-sm">
          <p>The delegation is active. These open tasks cannot be decided by your delegate because of the four-eyes rule (they started or already approved the document); they stay with you or your escalation path:</p>
          <ul className="list-disc pl-5">{blocked.map((b) => <li key={b.ref}><span className="font-medium">{b.ref}</span>: {b.reason}</li>)}</ul>
          <div className="flex justify-end"><Button variant="primary" onClick={onClose}>Close</Button></div>
        </div>
      </Dialog>
    );
  }
  return (
    <Dialog open title="Delegate my approvals" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-700">While you are away, your delegate can decide your approval tasks. Their decisions are recorded as made on
          your behalf, the four-eyes rule still applies to both of you, and you can revoke it at any time.</p>
        <Field label="Delegate (required)">
          {(id) => <Select id={id} required value={f.delegateId} onChange={set('delegateId')}
            options={[{ value: '', label: candidates.isLoading ? 'Loading…' : 'Choose a colleague' }, ...(candidates.data ?? []).map((c) => ({ value: c.id, label: `${c.name} (${c.email})` }))]} />}
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="From (required)">{(id) => <Input id={id} type="date" required min={today()} value={f.validFrom} onChange={set('validFrom')} />}</Field>
          <Field label="To (required)" hint="At most 90 days">{(id) => <Input id={id} type="date" required min={f.validFrom} value={f.validTo} onChange={set('validTo')} />}</Field>
          <Field label="Only for role" hint="Empty = all my roles">
            {(id) => <Select id={id} value={f.role} onChange={set('role')} options={[{ value: '', label: 'All my roles' }, ...roles.map((r) => ({ value: r, label: label(r) }))]} />}
          </Field>
          <Field label="Value limit (₹)" hint="Empty = no limit; tasks above it, or of unknown value, are excluded">
            {(id) => <Input id={id} type="number" min="1" step="1" value={f.limit} onChange={set('limit')} />}
          </Field>
        </div>
        <Field label="Reason (required)">{(id) => <Textarea id={id} required value={f.reason} onChange={set('reason')} placeholder="e.g. Annual leave 3 to 14 November" />}</Field>
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={cmd.isPending} disabled={!f.delegateId || f.reason.trim().length < 5}>Set delegation</Button>
        </div>
      </form>
    </Dialog>
  );
}

function RevokeDialog({ item, onClose }: { item: Delegation; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const cmd = useCommand(() => api.post(`/me/delegations/${item.id}/revoke`, { reason: reason.trim() }, { ifMatch: String(item.version) }), {
    success: 'Delegation revoked', onSuccess: onClose,
  });
  return (
    <Dialog open title="Revoke delegation" onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-slate-700">{item.delegator} → {item.delegate}, {date(item.validFrom)} to {date(item.validTo)}. The delegate loses access to your tasks immediately.</p>
        <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Back in the office earlier" />}</Field>
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2"><Button onClick={onClose}>Cancel</Button>
          <Button variant="danger" disabled={reason.trim().length < 3} busy={cmd.isPending} onClick={() => cmd.mutate()}>Revoke</Button></div>
      </div>
    </Dialog>
  );
}

export function DelegationsCard({ roles }: { roles: string[] }) {
  const { data, isLoading, error } = useApi<Mine>('/me/delegations');
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<Delegation | null>(null);
  const scope = (d: Delegation) => `${d.roles.length ? d.roles.map((r) => label(r)).join(', ') : 'All roles'}${d.valueLimitMinor ? ` · up to ₹${(d.valueLimitMinor / 100).toLocaleString('en-IN')}` : ''}`;
  const live = (d: Delegation) => d.status === 'ACTIVE' || d.status === 'SCHEDULED';
  return (
    <Card title="Delegation of authority" actions={<Button variant="primary" onClick={() => setCreating(true)}>Delegate my approvals</Button>}>
      <p className="mb-3 text-sm text-slate-600">Going on leave? Hand your approval tasks to a colleague for a period. They act on your behalf, and every decision shows both names in the audit trail.</p>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : data && (
        <div className="space-y-4">
          <div>
            <h3 className="mb-1 text-sm font-semibold text-slate-800">I delegated to</h3>
            <DataTable<Delegation & Record<string, unknown>> rows={data.given as (Delegation & Record<string, unknown>)[]} empty="You have not delegated your approvals" columns={[
              { key: 'delegate', header: 'Delegate', render: (d) => <span>{d.delegate}<br /><span className="text-xs text-slate-500">{d.delegateEmail}</span></span> },
              { key: 'period', header: 'Period', render: (d) => <span className="whitespace-nowrap text-xs">{date(d.validFrom)} → {date(d.validTo)}</span> },
              { key: 'scope', header: 'Scope', render: (d) => <span className="text-xs">{scope(d)}</span> },
              { key: 'status', header: 'Status', render: (d) => <StatusChip status={d.status} /> },
              { key: 'actions', header: '', render: (d) => (live(d) ? <Button variant="danger" onClick={() => setRevoking(d)}>Revoke</Button> : <span className="text-xs text-slate-500">{d.revokeReason ?? ''}</span>) },
            ]} />
          </div>
          <div>
            <h3 className="mb-1 text-sm font-semibold text-slate-800">Delegated to me</h3>
            <DataTable<Delegation & Record<string, unknown>> rows={data.received as (Delegation & Record<string, unknown>)[]} empty="Nobody has delegated to you" columns={[
              { key: 'delegator', header: 'From', render: (d) => <span>{d.delegator}<br /><span className="text-xs text-slate-500">{d.delegatorEmail}</span></span> },
              { key: 'period', header: 'Period', render: (d) => <span className="whitespace-nowrap text-xs">{date(d.validFrom)} → {date(d.validTo)}</span> },
              { key: 'scope', header: 'Scope', render: (d) => <span className="text-xs">{scope(d)}</span> },
              { key: 'status', header: 'Status', render: (d) => <StatusChip status={d.status} /> },
              { key: 'actions', header: '', render: (d) => (live(d) ? <Button onClick={() => setRevoking(d)}>Decline</Button> : null) },
            ]} />
          </div>
        </div>
      )}
      {creating && <NewDelegationDialog roles={roles} onClose={() => setCreating(false)} />}
      {revoking && <RevokeDialog item={revoking} onClose={() => setRevoking(null)} />}
    </Card>
  );
}
