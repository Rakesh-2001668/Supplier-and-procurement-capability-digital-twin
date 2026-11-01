'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, Dialog, Empty, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Evidence = { note: string; ref: string | null; by: string; at: string };
type Action = {
  id: string; seq: number; description: string; owner_id: string; due_date: string; status: string; evidence: Evidence[]; completed_at: string | null;
  reminders: number; owner: string | null; ownerEmail: string | null; overdue: boolean;
};
type Plan = {
  id: string; number: string; title: string; objective: string; status: string; start_date: string; target_date: string; metric: string | null;
  baseline_value: string | null; target_value: string | null; result_value: string | null; outcome: string | null; closed_at: string | null;
  supplier: string; capa: string | null; capaStatus: string | null; owner: string | null; currentValue: string | null; targetMet: boolean | null;
  reviewTask: string | null; actions: Action[]; progress: { done: number; total: number };
};
type MeFull = { userId: string; roles: string[] };
type UserRow = { id: string; email: string; name: string; active: boolean; supplierUser: boolean };

const METRICS = [
  { value: '', label: 'No scorecard metric' }, { value: 'OTIF', label: 'OTIF % (higher is better)' }, { value: 'PPM', label: 'PPM (lower is better)' },
  { value: 'INVOICE_ACCURACY', label: 'Invoice accuracy % (higher is better)' }, { value: 'RFQ_RESPONSE', label: 'RFQ response hours (lower is better)' },
  { value: 'ESG', label: 'ESG score (higher is better)' },
];
const newKey = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : String(Math.random()));

/** Pending workflow 29: development plans of a supplier, with actions, evidence, reminders and the review before closing. */
export function PlansCard({ code, manager }: { code: string; manager: boolean }) {
  const plans = useApi<Plan[]>(`/development-plans?supplier=${encodeURIComponent(code)}`);
  const me = useApi<MeFull>('/me');
  const [creating, setCreating] = useState(false);
  const [adding, setAdding] = useState<Plan | null>(null);
  const [working, setWorking] = useState<{ plan: Plan; action: Action; kind: 'evidence' | 'complete' | 'cancel' } | null>(null);
  const [cancelling, setCancelling] = useState<Plan | null>(null);
  const activate = useCommand((plan: Plan) => api.post(`/development-plans/${encodeURIComponent(plan.number)}/activate`), { success: 'Plan started – owners are notified and reminders are set' });
  const mine = me.data?.userId;

  return (
    <Card title="Development plans (SLM-07)" actions={manager && <Button onClick={() => setCreating(true)}>New plan</Button>}>
      {plans.isLoading ? <Loading /> : plans.error ? <ProblemBox error={plans.error} /> : !plans.data?.length ? (
        <Empty title="No development plans" hint={manager ? 'Start a plan from a CAPA or a weak scorecard: actions with owners, due dates and evidence.' : undefined} />
      ) : (
        <ul className="space-y-4">
          {plans.data.map((plan) => {
            const live = plan.status === 'ACTIVE';
            return (
              <li key={plan.id} className="rounded-lg border border-slate-200 p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-slate-900"><span className="font-mono text-xs text-slate-500">{plan.number}</span> {plan.title} <StatusChip status={plan.status} /></p>
                    <p className="mt-0.5 text-sm text-slate-600">{plan.objective}</p>
                    <p className="mt-0.5 text-xs text-slate-500">{date(plan.start_date)} to {date(plan.target_date)} · owner {plan.owner ?? '–'} · {plan.progress.done}/{plan.progress.total} actions done
                      {plan.capa && <> · CAPA {plan.capa} ({label(plan.capaStatus)})</>}</p>
                  </div>
                  {manager && (
                    <div className="flex flex-wrap gap-2">
                      {plan.status === 'DRAFT' && <Button variant="primary" busy={activate.isPending && activate.variables?.id === plan.id} onClick={() => activate.mutate(plan)}>Start plan</Button>}
                      {(plan.status === 'DRAFT' || live) && <Button onClick={() => setAdding(plan)}>Add action</Button>}
                      {(plan.status === 'DRAFT' || live) && <Button variant="danger" onClick={() => setCancelling(plan)}>Cancel plan</Button>}
                    </div>
                  )}
                </div>
                {plan.metric && (
                  <p className="mt-2 rounded bg-slate-50 px-3 py-1.5 text-xs text-slate-700">
                    {label(plan.metric)}: baseline {plan.baseline_value ?? '–'} · now {plan.status === 'COMPLETED' ? (plan.result_value ?? '–') : (plan.currentValue ?? '–')} · target {plan.target_value ?? '–'}
                    {plan.targetMet !== null && <span className={`ml-2 font-semibold ${plan.targetMet ? 'text-emerald-700' : 'text-amber-700'}`}>{plan.targetMet ? 'target met' : 'target not met'}</span>}
                  </p>
                )}
                {live && plan.reviewTask && (
                  <p className="mt-2 rounded border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-900">
                    All actions are closed: the plan is waiting for the supplier manager&apos;s review. <Link href="/pic/tasks" className="font-semibold underline">Open the task inbox</Link>
                    {plan.capa && plan.capaStatus !== 'CLOSED' && ` · the linked CAPA ${plan.capa} must be verified and closed first`}.
                  </p>
                )}
                {plan.outcome && <p className="mt-2 text-xs text-slate-600">Outcome: {plan.outcome}{plan.closed_at ? ` · ${dateTime(plan.closed_at)}` : ''}</p>}
                <ol className="mt-3 divide-y divide-slate-100 text-sm">
                  {plan.actions.map((a) => {
                    const canWork = live && a.status === 'OPEN' && (manager || a.owner_id === mine);
                    return (
                      <li key={a.id} className="py-2">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p><span className="font-mono text-xs text-slate-500">{a.seq}.</span> {a.description} <StatusChip status={a.overdue ? 'OVERDUE' : a.status} /></p>
                            <p className="text-xs text-slate-500">Owner {a.owner ?? a.owner_id} · due {date(a.due_date)}{a.completed_at ? ` · done ${dateTime(a.completed_at)}` : ''}{a.reminders ? ` · ${a.reminders} reminder(s) sent` : ''}</p>
                            {a.evidence.length > 0 && (
                              <ul className="mt-1 list-disc pl-5 text-xs text-slate-600">
                                {a.evidence.map((e, i) => <li key={i}>{e.note}{e.ref ? ` (${e.ref})` : ''} – {e.by}, {dateTime(e.at)}</li>)}
                              </ul>
                            )}
                          </div>
                          {a.status === 'OPEN' && (
                            <div className="flex flex-wrap gap-1.5">
                              {canWork && <Button onClick={() => setWorking({ plan, action: a, kind: 'evidence' })}>Add evidence</Button>}
                              {canWork && <Button variant="primary" disabled={!a.evidence.length} title={a.evidence.length ? undefined : 'Add evidence first'} onClick={() => setWorking({ plan, action: a, kind: 'complete' })}>Complete</Button>}
                              {manager && (plan.status === 'DRAFT' || live) && <Button variant="danger" onClick={() => setWorking({ plan, action: a, kind: 'cancel' })}>Cancel action</Button>}
                            </div>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </li>
            );
          })}
        </ul>
      )}
      {creating && <CreatePlanDialog code={code} onClose={() => setCreating(false)} />}
      {adding && <AddActionDialog plan={adding} onClose={() => setAdding(null)} />}
      {working && <ActionDialog plan={working.plan} action={working.action} kind={working.kind} onClose={() => setWorking(null)} />}
      {cancelling && <CancelPlanDialog plan={cancelling} onClose={() => setCancelling(null)} />}
    </Card>
  );
}

/** Owner picker: the user directory when the caller may read it, otherwise a plain user id (with "me" as a shortcut). */
function OwnerField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const users = useApi<UserRow[]>('/admin/users');
  const me = useApi<MeFull>('/me');
  return (
    <Field label="Owner" hint={users.error ? 'The user directory is not available to your role: enter the user id' : undefined}>{(id) => users.data ? (
      <Select id={id} value={value} onChange={(e) => onChange(e.target.value)} options={[
        { value: '', label: 'Choose an owner' }, ...users.data.filter((u) => u.active).map((u) => ({ value: u.id, label: `${u.name} · ${u.email}${u.supplierUser ? ' (supplier)' : ''}` })),
      ]} />
    ) : (
      <div className="flex gap-2">
        <Input id={id} value={value} onChange={(e) => onChange(e.target.value.trim())} placeholder="user id (UUID)" className="font-mono text-xs" />
        {me.data && <Button onClick={() => onChange(me.data?.userId ?? '')}>Me</Button>}
      </div>
    )}</Field>
  );
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
type Draft = { key: string; description: string; owner: string; due: string };

function CreatePlanDialog({ code, onClose }: { code: string; onClose: () => void }) {
  const [title, setTitle] = useState('');
  const [objective, setObjective] = useState('');
  const [start, setStart] = useState('');
  const [target, setTarget] = useState('');
  const [capa, setCapa] = useState('');
  const [metric, setMetric] = useState('');
  const [metricTarget, setMetricTarget] = useState('');
  const [actions, setActions] = useState<Draft[]>([{ key: newKey(), description: '', owner: '', due: '' }]);
  const update = (key: string, patch: Partial<Draft>) => setActions((list) => list.map((a) => (a.key === key ? { ...a, ...patch } : a)));
  const actionsOk = actions.every((a) => a.description.trim().length >= 3 && UUID.test(a.owner) && a.due && a.due >= start && a.due <= target);
  const valid = title.trim().length >= 3 && objective.trim().length >= 5 && !!start && !!target && target > start && (!!metric === !!metricTarget) && actionsOk;
  const create = useCommand(() => api.post<{ number: string }>(`/suppliers/${encodeURIComponent(code)}/development-plans`, {
    title: title.trim(), objective: objective.trim(), start_date: start, target_date: target, capa: capa.trim() || undefined, metric: metric || undefined,
    target_value: metric ? metricTarget : undefined, actions: actions.map((a) => ({ description: a.description.trim(), owner_id: a.owner, due_date: a.due })),
  }), { success: (r) => `${r.number} created as a draft – start it to notify the owners`, onSuccess: onClose });
  return (
    <Dialog open title={`New development plan – ${code}`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="md:col-span-2"><Field label="Title" required>{(id) => <Input id={id} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Delivery recovery" />}</Field></div>
        <div className="md:col-span-2"><Field label="Objective" required>{(id) => <Textarea id={id} value={objective} onChange={(e) => setObjective(e.target.value)} placeholder="e.g. Raise OTIF to 95 percent by June" />}</Field></div>
        <Field label="Start date" required>{(id) => <Input id={id} type="date" value={start} onChange={(e) => setStart(e.target.value)} />}</Field>
        <Field label="Target date" required error={start && target && target <= start ? 'Must be after the start date' : undefined}>{(id) => <Input id={id} type="date" value={target} onChange={(e) => setTarget(e.target.value)} />}</Field>
        <Field label="Linked CAPA (optional)" hint="CAPA number; the plan completes only when it is verified closed">{(id) => <Input id={id} value={capa} onChange={(e) => setCapa(e.target.value.toUpperCase())} placeholder="CAPA-301" />}</Field>
        <Field label="Scorecard metric (optional)">{(id) => <Select id={id} value={metric} onChange={(e) => setMetric(e.target.value)} options={METRICS} />}</Field>
        {metric && <Field label="Target value" required>{(id) => <Input id={id} type="number" step="0.01" value={metricTarget} onChange={(e) => setMetricTarget(e.target.value)} />}</Field>}
      </div>
      <p className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Actions</p>
      <div className="space-y-3">
        {actions.map((a, i) => (
          <div key={a.key} className="rounded-lg border border-slate-200 p-3">
            <div className="grid gap-3 md:grid-cols-2">
              <div className="md:col-span-2"><Field label={`Action ${i + 1}`}>{(id) => <Input id={id} value={a.description} onChange={(e) => update(a.key, { description: e.target.value })} />}</Field></div>
              <OwnerField value={a.owner} onChange={(v) => update(a.key, { owner: v })} />
              <Field label="Due date" error={a.due && start && target && (a.due < start || a.due > target) ? 'Within the plan dates' : undefined}>{(id) => <Input id={id} type="date" value={a.due} onChange={(e) => update(a.key, { due: e.target.value })} />}</Field>
            </div>
            {actions.length > 1 && <Button variant="ghost" className="mt-2" onClick={() => setActions((list) => list.filter((x) => x.key !== a.key))}>Remove action</Button>}
          </div>
        ))}
      </div>
      <Button className="mt-3" onClick={() => setActions((list) => [...list, { key: newKey(), description: '', owner: '', due: '' }])}>Add another action</Button>
      <ProblemBox error={create.error} />
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!valid} busy={create.isPending} onClick={() => create.mutate()}>Create plan</Button>
      </div>
    </Dialog>
  );
}

function AddActionDialog({ plan, onClose }: { plan: Plan; onClose: () => void }) {
  const [description, setDescription] = useState('');
  const [owner, setOwner] = useState('');
  const [due, setDue] = useState('');
  const add = useCommand(() => api.post(`/development-plans/${encodeURIComponent(plan.number)}/actions`, { description: description.trim(), owner_id: owner, due_date: due }),
    { success: 'Action added', onSuccess: onClose });
  const valid = description.trim().length >= 3 && UUID.test(owner) && !!due && due >= plan.start_date && due <= plan.target_date;
  return (
    <Dialog open title={`Add action – ${plan.number}`} onClose={onClose}>
      <div className="grid gap-3">
        <Field label="Action" required>{(id) => <Input id={id} value={description} onChange={(e) => setDescription(e.target.value)} />}</Field>
        <OwnerField value={owner} onChange={setOwner} />
        <Field label="Due date" required hint={`Between ${date(plan.start_date)} and ${date(plan.target_date)}`}>{(id) => <Input id={id} type="date" value={due} onChange={(e) => setDue(e.target.value)} />}</Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!valid} busy={add.isPending} onClick={() => add.mutate()}>Add action</Button>
      </div>
    </Dialog>
  );
}

function ActionDialog({ plan, action, kind, onClose }: { plan: Plan; action: Action; kind: 'evidence' | 'complete' | 'cancel'; onClose: () => void }) {
  const [note, setNote] = useState('');
  const [ref, setRef] = useState('');
  const base = `/development-plans/${encodeURIComponent(plan.number)}/actions/${action.seq}`;
  const run = useCommand(() => (kind === 'evidence' ? api.post(`${base}/evidence`, { note: note.trim(), ref: ref.trim() || undefined })
    : kind === 'complete' ? api.post(`${base}/complete`, { note: note.trim() }) : api.post(`${base}/cancel`, { reason: note.trim() })), {
    success: kind === 'evidence' ? 'Evidence added' : kind === 'complete' ? 'Action completed' : 'Action cancelled', onSuccess: onClose });
  const title = kind === 'evidence' ? 'Add evidence' : kind === 'complete' ? 'Complete action' : 'Cancel action';
  return (
    <Dialog open title={`${title} – ${plan.number} / ${action.seq}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">{action.description}</p>
      <div className="grid gap-3">
        <Field label={kind === 'cancel' ? 'Reason (required)' : kind === 'evidence' ? 'What does the evidence show? (required)' : 'Completion note'}>{(id) => (
          <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} />
        )}</Field>
        {kind === 'evidence' && <Field label="Document or reference" hint="e.g. roster number, report id, certificate number">{(id) => <Input id={id} value={ref} onChange={(e) => setRef(e.target.value)} />}</Field>}
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Close</Button>
        <Button variant={kind === 'cancel' ? 'danger' : 'primary'} disabled={kind !== 'complete' && note.trim().length < 3} busy={run.isPending} onClick={() => run.mutate()}>{title}</Button>
      </div>
    </Dialog>
  );
}

function CancelPlanDialog({ plan, onClose }: { plan: Plan; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const cancel = useCommand(() => api.post(`/development-plans/${encodeURIComponent(plan.number)}/cancel`, { reason: reason.trim() }),
    { success: `${plan.number} cancelled`, onSuccess: onClose });
  return (
    <Dialog open title={`Cancel plan ${plan.number}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-700">Open actions are cancelled, reminders stop and any review task is withdrawn.</p>
      <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Back</Button>
        <Button variant="danger" disabled={reason.trim().length < 3} busy={cancel.isPending} onClick={() => cancel.mutate()}>Cancel plan</Button>
      </div>
    </Dialog>
  );
}
