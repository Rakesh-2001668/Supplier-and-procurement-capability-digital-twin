'use client';

import Link from 'next/link';
import { FormEvent, useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, Loading, PageHeader, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, inr, label, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { hasRole, useSessionUser } from '../invoices/_components';

type Agent = { id: string; code: string; name: string; module: string; purpose: string; autonomy_level: string; run_as_role: string;
  value_limit_minor: number | null; categories: string[]; kill_switch: boolean; model_version: string; min_acceptance_rate: string | null };
type Run = { id: string; agent_code: string; object_type: string; object_ref: string | null; action_taken: string; confidence: string | null;
  model_version: string; created_at: string; evidence: unknown; output: unknown; inputs: unknown; denial_reason: string | null;
  autonomy_level: string; human_feedback: string | null };

const AUTONOMY: { level: string; name: string; text: string }[] = [
  { level: 'L0', name: 'Off', text: 'Agent does nothing.' },
  { level: 'L1', name: 'Recommend', text: 'Suggests; a human does the work.' },
  { level: 'L2', name: 'Draft', text: 'Prepares the document; a human submits.' },
  { level: 'L3', name: 'Act with review', text: 'Acts; a human reviews afterwards.' },
  { level: 'L4', name: 'Autonomous within policy', text: 'Acts alone inside value and policy limits.' },
];
const autonomyName = (l: string) => AUTONOMY.find((a) => a.level === l)?.name ?? l;
// Agents that scan data on demand (POST /agents/{code}/runs); the others run on their trigger events.
const RUNNABLE = ['DEMAND_SENSING', 'SUPPLIER_RISK', 'SPEND_CLASSIFICATION', 'SOURCING_STRATEGY'];

type Recommendation = { id: string; agent: string; objectType: string; objectRef: string | null; title: string; rationale: string; proposal: unknown;
  deepLink: string | null; valueAtRiskMinor: number | null; role: string; status: string; createdAt: string; feedback: string | null };
type RunResult = { agent: string; result: Record<string, unknown> };
const resultText = (result: Record<string, unknown>) =>
  Object.entries(result).map(([k, v]) => `${label(k)}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`).join(' · ') || 'completed';

function Json({ value }: { value: unknown }) {
  if (value === null || value === undefined || (Array.isArray(value) && value.length === 0)) return <span className="text-slate-400">–</span>;
  if (Array.isArray(value) && value.every((v) => typeof v === 'string')) return <span className="text-xs">{(value as string[]).join(' · ')}</span>;
  return <pre className="max-w-xs overflow-x-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-1.5 font-mono text-[11px] text-slate-700">{JSON.stringify(value, null, 1)}</pre>;
}

function Runs({ code }: { code: string }) {
  const { data, isLoading, error } = useApi<Run[]>(`/agents/${code}/runs`);
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  return (
    <DataTable<Run> rows={data ?? []} empty="This agent has not run yet" columns={[
      { key: 'created_at', header: 'When', render: (r) => <span className="whitespace-nowrap">{dateTime(r.created_at)}</span> },
      { key: 'object_ref', header: 'Object', render: (r) => <span><span className="font-medium">{r.object_ref ?? '–'}</span><br /><span className="text-xs text-slate-500">{label(r.object_type)}</span></span> },
      { key: 'action_taken', header: 'Action', render: (r) => <StatusChip status={r.action_taken} /> },
      { key: 'confidence', header: 'Confidence', align: 'right', render: (r) => (r.confidence === null ? '–' : `${Math.round(Number(r.confidence) * 100)}%`) },
      { key: 'model_version', header: 'Model', render: (r) => <span className="font-mono text-xs">{r.model_version}</span> },
      { key: 'evidence', header: 'Evidence', render: (r) => <Json value={r.evidence} /> },
      { key: 'output', header: 'Output', render: (r) => <Json value={r.output} /> },
      { key: 'denial_reason', header: 'Denial', render: (r) => (r.denial_reason ? <span className="text-red-800">{r.denial_reason}</span> : '–') },
    ]} />
  );
}

function KillSwitchDialog({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const turnOn = !agent.kill_switch;
  const [reason, setReason] = useState('');
  const cmd = useCommand((body: { on: boolean; reason: string }) => api.put(`/agents/${agent.code}/kill-switch`, body), {
    success: `${agent.code}: kill switch ${turnOn ? 'on, agent stopped' : 'off, agent resumed'}`, onSuccess: onClose,
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (reason.trim().length < 3) return;
    cmd.mutate({ on: turnOn, reason: reason.trim() });
  }
  return (
    <Dialog open title={`${turnOn ? 'Stop' : 'Resume'} ${agent.name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <p className="text-sm text-slate-700">
          {turnOn
            ? 'Turning the kill switch on stops this agent immediately. Its work falls back to the human role it runs as.'
            : 'Turning the kill switch off lets this agent act again at its configured autonomy level.'}
          {' '}The change and your reason are written to the audit trail. Only the CPO or the tenant administrator can do this.
        </p>
        <Field label="Reason (required)" hint="At least 3 characters.">
          {(id) => <Textarea id={id} required value={reason} onChange={(e) => setReason(e.target.value)} placeholder={turnOn ? 'e.g. Acceptance rate fell below threshold' : 'e.g. Model retrained and re-validated'} />}
        </Field>
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant={turnOn ? 'danger' : 'primary'} busy={cmd.isPending} disabled={reason.trim().length < 3}>
            {turnOn ? 'Turn kill switch on' : 'Turn kill switch off'}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export default function Agents() {
  const { data, isLoading, error } = useApi<Agent[]>('/agents');
  const user = useSessionUser();
  const canManage = hasRole(user, 'CPO', 'TENANT_ADMIN');
  const [selected, setSelected] = useState<string | null>(null);
  const [switching, setSwitching] = useState<Agent | null>(null);
  const [editing, setEditing] = useState<Agent | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<RunResult | null>(null);
  const run = useCommand((code: string) => api.post<RunResult>(`/agents/${code}/runs`), {
    success: (r) => `${r.agent} ran · ${resultText(r.result)}`,
    onSuccess: (r) => { setLastRun(r); setSelected(r.agent); },
  });
  const current = data?.find((a) => a.code === selected) ?? null;

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="AIX-03 · Agent console" title="AI agents"
        subtitle="Every agent runs as a named role with a value limit and an autonomy level. Each run is logged with its evidence, confidence and model version." />

      <Card title="Autonomy levels">
        <ol className="grid gap-2 text-sm sm:grid-cols-5">
          {AUTONOMY.map((a) => (
            <li key={a.level} className="rounded-lg border border-slate-200 px-3 py-2">
              <p><span className="rounded bg-[#0B1020] px-1.5 py-0.5 font-mono text-[11px] text-white">{a.level}</span> <span className="font-semibold">{a.name}</span></p>
              <p className="mt-1 text-xs text-slate-600">{a.text}</p>
            </li>
          ))}
        </ol>
      </Card>

      <Card title="Agents">
        {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : (
          <DataTable<Agent> rows={data ?? []} empty="No agents registered" columns={[
            { key: 'code', header: 'Agent', render: (r) => (
              <button type="button" onClick={() => setSelected(r.code)} aria-pressed={selected === r.code} className="text-left">
                <span className={`font-mono text-xs font-medium hover:underline ${selected === r.code ? 'text-[#0B1020] underline' : 'text-[#1A56DB]'}`}>{r.code}</span>
                <span className="block text-sm text-slate-900">{r.name}</span>
              </button>
            ) },
            { key: 'module', header: 'Module' },
            { key: 'purpose', header: 'Purpose', className: 'min-w-[220px] text-slate-700' },
            { key: 'autonomy_level', header: 'Autonomy', render: (r) => <span className="whitespace-nowrap"><span className="font-mono font-semibold">{r.autonomy_level}</span> <span className="text-xs text-slate-500">{autonomyName(r.autonomy_level)}</span></span> },
            { key: 'run_as_role', header: 'Runs as', render: (r) => label(r.run_as_role) },
            { key: 'value_limit_minor', header: 'Value limit', align: 'right', render: (r) => (r.value_limit_minor === null ? 'No limit' : inr(r.value_limit_minor)) },
            { key: 'model_version', header: 'Model', render: (r) => <span className="font-mono text-xs">{r.model_version}</span> },
            { key: 'kill_switch', header: 'Kill switch', render: (r) => (
              <div className="flex items-center gap-2">
                <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset ${r.kill_switch ? 'bg-red-50 text-red-800 ring-red-200' : 'bg-emerald-50 text-emerald-800 ring-emerald-200'}`}>
                  {r.kill_switch ? 'Stopped' : 'Running'}
                </span>
                <button type="button" role="switch" aria-checked={r.kill_switch} aria-label={`Kill switch for ${r.name}`} onClick={() => setSwitching(r)}
                  className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1A56DB] ${r.kill_switch ? 'bg-red-600' : 'bg-slate-300'}`}>
                  <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition ${r.kill_switch ? 'translate-x-4' : 'translate-x-0.5'}`} />
                </button>
              </div>
            ) },
            { key: 'actions', header: '', render: (r) => (
              <div className="flex flex-wrap justify-end gap-2">
                {RUNNABLE.includes(r.code) && (
                  <Button disabled={r.kill_switch || run.isPending} busy={run.isPending && running === r.code} title={r.kill_switch ? 'Kill switch is on' : undefined}
                    onClick={() => { setRunning(r.code); run.mutate(r.code); }}>Run now</Button>
                )}
                {canManage && <Button variant="ghost" onClick={() => setEditing(r)}>Autonomy</Button>}
              </div>
            ) },
          ]} />
        )}
        {lastRun && (
          <p role="status" className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
            Last on-demand run: <span className="font-mono">{lastRun.agent}</span> · {resultText(lastRun.result)}
          </p>
        )}
      </Card>

      <RecommendationsInbox />

      {current ? (
        <Card title={<span>Runs · <span className="font-mono">{current.code}</span> · {current.name}</span>}
          actions={<Button variant="ghost" onClick={() => setSelected(null)}>Close</Button>}>
          <Runs code={current.code} />
        </Card>
      ) : data?.length ? <p className="text-sm text-slate-500">Select an agent to see its run log.</p> : null}

      {switching && <KillSwitchDialog agent={switching} onClose={() => setSwitching(null)} />}
      {editing && <AutonomyDialog agent={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------- autonomy editor (agents:manage: CPO, tenant administrator)
function AutonomyDialog({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const [level, setLevel] = useState(agent.autonomy_level);
  const [limit, setLimit] = useState(agent.value_limit_minor === null ? '' : String(agent.value_limit_minor / 100));
  const [categories, setCategories] = useState((agent.categories ?? []).join(', '));
  const [killSwitch, setKillSwitch] = useState(agent.kill_switch);
  const [reason, setReason] = useState('');
  const [invalid, setInvalid] = useState<string | null>(null);
  const cmd = useCommand((body: Record<string, unknown>) => api.put(`/agents/${agent.code}/autonomy`, body), {
    success: `${agent.code}: autonomy updated`, onSuccess: onClose,
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (reason.trim().length < 3) { setInvalid('Give a reason of at least 3 characters.'); return; }
    if (limit.trim() && (Number.isNaN(Number(limit)) || Number(limit) <= 0)) { setInvalid('Value limit must be a positive rupee amount, or empty.'); return; }
    setInvalid(null);
    const cats = categories.split(',').map((c) => c.trim()).filter(Boolean);
    cmd.mutate({
      level, reason: reason.trim(), kill_switch: killSwitch,
      value_limit_minor: limit.trim() ? rupeesToMinor(limit) : undefined,
      categories: cats.length || agent.categories?.length ? cats : undefined,
    });
  }
  return (
    <Dialog open title={`Autonomy · ${agent.name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Autonomy level" hint={AUTONOMY.find((a) => a.level === level)?.text}>
            {(id) => <Select id={id} value={level} onChange={(e) => setLevel(e.target.value)} options={AUTONOMY.map((a) => ({ value: a.level, label: `${a.level} · ${a.name}` }))} />}
          </Field>
          <Field label="Value limit (₹)" hint={agent.value_limit_minor === null ? 'Currently no limit. Empty keeps it.' : `Currently ${inr(agent.value_limit_minor)}. Empty keeps it.`}>
            {(id) => <Input id={id} inputMode="decimal" value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="e.g. 500000" />}
          </Field>
        </div>
        <Field label="Categories" hint="Comma-separated category codes the agent may act in (L4 needs at least one), e.g. ALU-DIECAST, MRO">
          {(id) => <Input id={id} value={categories} onChange={(e) => setCategories(e.target.value)} />}
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="h-4 w-4" checked={killSwitch} onChange={(e) => setKillSwitch(e.target.checked)} />
          Kill switch on (agent stopped)
        </label>
        <Field label="Reason (required)" hint="Written to the audit trail with the before and after settings.">
          {(id) => <Textarea id={id} required value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Acceptance above 85% for two quarters; raise to L3" />}
        </Field>
        {invalid && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">{invalid}</p>}
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={cmd.isPending}>Save autonomy</Button>
        </div>
      </form>
    </Dialog>
  );
}

// ---------------------------------------------------------------- recommendations inbox (recommend, a human decides)
function RecommendationsInbox() {
  const user = useSessionUser();
  const [status, setStatus] = useState('OPEN');
  const [rejecting, setRejecting] = useState<Recommendation | null>(null);
  const [deciding, setDeciding] = useState<string | null>(null);
  const { data, isLoading, error } = useApi<Recommendation[]>(`/recommendations?status=${status}`);
  const accept = useCommand((id: string) => api.post(`/recommendations/${id}/feedback`, { accepted: true }), {
    success: 'Recommendation accepted. Follow its link to act; accepting never executes the action by itself.',
  });
  const canDecide = (r: Recommendation) => hasRole(user, r.role, 'CPO');
  return (
    <Card title="Recommendations inbox" actions={
      <Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}
        options={[{ value: 'OPEN', label: 'Open' }, { value: 'ACCEPTED', label: 'Accepted' }, { value: 'REJECTED', label: 'Rejected' }]} />
    }>
      <p className="mb-3 text-sm text-slate-600">Recommendations agents raised for your role. Accept or reject each one; a rejection needs a reason, which feeds the
        agent&apos;s acceptance rate. Accepting does not act on its own: follow the link to do the work.</p>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : (
        <DataTable<Recommendation> rows={data ?? []} empty={`No ${status.toLowerCase()} recommendations for your role`} columns={[
          { key: 'createdAt', header: 'Raised', render: (r) => <span className="whitespace-nowrap">{dateTime(r.createdAt)}</span> },
          { key: 'agent', header: 'Agent', render: (r) => <span className="font-mono text-xs">{r.agent}</span> },
          { key: 'title', header: 'Recommendation', className: 'min-w-[260px] max-w-lg', render: (r) => (
            <span>
              {r.deepLink ? <Link href={r.deepLink} prefetch={false} className="font-medium text-[#1A56DB] hover:underline">{r.title}</Link> : <span className="font-medium">{r.title}</span>}
              <span className="mt-0.5 block text-xs text-slate-600">{r.rationale}</span>
            </span>
          ) },
          { key: 'role', header: 'For', render: (r) => <span className="text-xs">{label(r.role)}</span> },
          { key: 'valueAtRiskMinor', header: 'Value', align: 'right', render: (r) => inr(r.valueAtRiskMinor) },
          { key: 'status', header: 'Status', render: (r) => (
            <span><StatusChip status={r.status} />{r.feedback && <span className="mt-0.5 block max-w-[200px] text-xs text-slate-500">“{r.feedback}”</span>}</span>
          ) },
          { key: 'action', header: '', render: (r) => r.status === 'OPEN' && canDecide(r) ? (
            <div className="flex gap-2">
              <Button variant="primary" busy={accept.isPending && deciding === r.id} disabled={accept.isPending}
                onClick={() => { setDeciding(r.id); accept.mutate(r.id); }}>Accept</Button>
              <Button variant="danger" onClick={() => setRejecting(r)}>Reject</Button>
            </div>
          ) : null },
        ]} />
      )}
      {rejecting && <RejectDialog rec={rejecting} onClose={() => setRejecting(null)} />}
    </Card>
  );
}

function RejectDialog({ rec, onClose }: { rec: Recommendation; onClose: () => void }) {
  const [comment, setComment] = useState('');
  const cmd = useCommand(() => api.post(`/recommendations/${rec.id}/feedback`, { accepted: false, comment: comment.trim() }), {
    success: 'Recommendation rejected; the reason is logged against the agent run', onSuccess: onClose,
  });
  return (
    <Dialog open title={`Reject: ${rec.title}`} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-slate-700">{rec.rationale}</p>
        <Field label="Why is it wrong? (required)" hint="The reason trains the agent and is written to the audit trail.">
          {(id) => <Textarea id={id} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="e.g. Customer schedule SO-88415 already covers the pull-in" />}
        </Field>
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="danger" disabled={!comment.trim()} busy={cmd.isPending} onClick={() => cmd.mutate()}>Reject</Button>
        </div>
      </div>
    </Dialog>
  );
}
