'use client';

import { FormEvent, useState } from 'react';
import { Button, Card, Dialog, Field, Loading, ProblemBox, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Switch = { enabled: boolean; reason: string | null; changedAt: string | null; version: number };
export type Acceptance = { code: string; events: number; accepted: number; rate: number | null; minFeedback: number; minimum: number; killSwitch: boolean;
  suspendedAt: string | null; suspendedBy: string | null; suspensionReason: string | null };

function SwitchDialog({ state, onClose }: { state: Switch; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const turnOff = state.enabled;
  const cmd = useCommand((body: { enabled: boolean; reason: string }) => api.put('/admin/ai/switch', body, { ifMatch: String(state.version) }), {
    success: turnOff ? 'AI switched off for the organisation' : 'AI switched on', onSuccess: onClose,
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    cmd.mutate({ enabled: !turnOff, reason: reason.trim() });
  }
  return (
    <Dialog open title={turnOff ? 'Switch AI off for the whole organisation' : 'Switch AI on'} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <p className="text-sm text-slate-700">{turnOff
          ? 'Every AI agent stops at once, whatever its own switch says: no drafts, recommendations or automatic actions. Work falls back to the people who own it.'
          : 'Agents may act again at their configured autonomy level; agents with their own kill switch on stay stopped.'}
          {' '}The change and your reason are written to the audit trail and the CPO and administrators are notified.</p>
        <Field label="Reason (required)" hint="At least 5 characters.">{(id) => <Textarea id={id} required value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant={turnOff ? 'danger' : 'primary'} busy={cmd.isPending} disabled={reason.trim().length < 5}>{turnOff ? 'Switch AI off' : 'Switch AI on'}</Button>
        </div>
      </form>
    </Dialog>
  );
}

export function AiSwitchCard({ canManage }: { canManage: boolean }) {
  const { data, isLoading, error } = useApi<Switch>('/admin/ai/switch');
  const [open, setOpen] = useState(false);
  if (isLoading) return <Card title="AI switch"><Loading /></Card>;
  if (error || !data) return <Card title="AI switch"><ProblemBox error={error} /></Card>;
  return (
    <Card title="AI switch (whole organisation)" actions={<StatusChip status={data.enabled ? 'ACTIVE' : 'STOPPED'} />}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-3xl text-sm text-slate-700">
          {data.enabled
            ? 'AI is on. An agent is suspended automatically when fewer than 70% of its suggestions are accepted over at least 20 reviewed ones; the CPO and administrators are told.'
            : `AI is off for the whole organisation${data.reason ? `: ${data.reason}` : ''}${data.changedAt ? ` (since ${dateTime(data.changedAt)})` : ''}. No agent acts.`}
        </p>
        {canManage && <Button variant={data.enabled ? 'danger' : 'primary'} onClick={() => setOpen(true)}>{data.enabled ? 'Switch AI off' : 'Switch AI on'}</Button>}
      </div>
      {open && <SwitchDialog state={data} onClose={() => setOpen(false)} />}
    </Card>
  );
}

export function AcceptanceCell({ item }: { item?: Acceptance }) {
  if (!item) return <span className="text-slate-400">–</span>;
  if (item.rate === null) return <span className="text-xs text-slate-500">{item.events} of {item.minFeedback} reviews</span>;
  const low = item.rate < item.minimum;
  return <span className={`text-xs ${low ? 'font-semibold text-red-800' : 'text-slate-700'}`}>{Math.round(item.rate * 100)}% of {item.events}<br />min {Math.round(item.minimum * 100)}%</span>;
}

export function SuspensionNote({ item }: { item?: Acceptance }) {
  if (!item?.killSwitch || !item.suspensionReason) return null;
  return (
    <p className="mt-1 max-w-[220px] text-[11px] text-red-800">
      {item.suspendedBy === 'AUTO' ? 'Suspended automatically' : 'Stopped'} {item.suspendedAt ? dateTime(item.suspendedAt) : ''}: {item.suspensionReason}
    </p>
  );
}
