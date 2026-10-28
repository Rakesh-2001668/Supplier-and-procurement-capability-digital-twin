'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Card, DataTable, Dialog, Empty, Loading, PageHeader, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { dateTime, label } from '@/lib/pic/format';
import { useApi, useList } from '@/lib/pic/hooks';
import { docHref } from '@/lib/pic/links';

type DefStep = { id: string; lane: string; name: string; type: string; screen: string | null };
type Definition = { key: string; flow: string; version: number; name: string; steps: DefStep[]; branches: string | null };
type Instance = { id: string; process_key: string; business_type: string; business_ref: string; status: string; current_step: string | null;
  started_at: string; ended_at: string | null };
type PathStep = { step: string; name: string; lane: string; type: string; status: string; actor: string | null; outcome: string | null; at: string };
type History = { id: string; process: string; flow: string; name: string; version: number; business: { type: string; id: string; ref: string };
  status: string; currentStep: string | null; startedAt: string; endedAt: string | null; path: PathStep[];
  tasks: { id: string; name: string; role: string; status: string; decision: string | null; comment: string | null; completedAt: string | null }[] };

const STATUSES = ['', 'RUNNING', 'COMPLETED', 'CANCELLED', 'REJECTED'];

const TYPE_STYLE: Record<string, string> = {
  event: 'rounded-full border-2 border-slate-400 bg-white',
  user: 'rounded-md border border-blue-300 bg-blue-50',
  system: 'rounded-md border border-slate-300 bg-slate-100',
  gateway: 'rounded-md border-2 border-dashed border-amber-400 bg-amber-50',
};
const TYPE_ICON: Record<string, string> = { event: '○', user: '👤', system: '⚙', gateway: '◇' };

/** Compact swimlane: one row per lane, one column per step (ordered by step id). */
function Swimlane({ def, visited, active }: { def: Definition; visited?: Set<string>; active?: string | null }) {
  const steps = [...def.steps].sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }));
  const lanes: string[] = [];
  for (const s of steps) if (!lanes.includes(s.lane)) lanes.push(s.lane);
  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-max gap-px rounded-lg border border-slate-200 bg-slate-200 text-xs"
        style={{ gridTemplateColumns: `150px repeat(${steps.length}, minmax(112px, 1fr))` }}>
        {lanes.map((lane) => (
          <div key={lane} className="contents">
            <div className="flex items-center bg-slate-50 px-2 py-2 font-semibold text-slate-700">{lane}</div>
            {steps.map((s) => {
              if (s.lane !== lane) return <div key={s.id} className="bg-white" />;
              const isActive = active === s.id;
              const done = visited?.has(s.id) && !isActive;
              return (
                <div key={s.id} className="bg-white p-1.5">
                  <div className={`${TYPE_STYLE[s.type] ?? TYPE_STYLE.system} px-2 py-1 ${isActive ? 'ring-2 ring-amber-500' : done ? 'ring-2 ring-emerald-500' : ''} ${visited && !visited.has(s.id) ? 'opacity-50' : ''}`}
                    title={`${s.id} · ${s.type}${s.screen ? ` · screen ${s.screen}` : ''}`}>
                    <p className="font-mono text-[10px] text-slate-500"><span aria-hidden>{TYPE_ICON[s.type] ?? ''} </span>{s.id} · {s.type}</p>
                    <p className="font-medium leading-tight text-slate-900">{s.name}</p>
                    {isActive && <p className="mt-0.5 text-[10px] font-semibold uppercase text-amber-700">Token here</p>}
                    {done && <p className="mt-0.5 text-[10px] font-semibold uppercase text-emerald-700">✓ Passed</p>}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
      {def.branches && <p className="mt-2 text-xs text-slate-600"><span className="font-semibold">Branches: </span>{def.branches}</p>}
    </div>
  );
}

function Legend() {
  return (
    <ul className="flex flex-wrap gap-3 text-xs text-slate-600">
      {(['event', 'user', 'system', 'gateway'] as const).map((t) => (
        <li key={t} className="flex items-center gap-1.5">
          <span className={`inline-block h-4 w-6 ${TYPE_STYLE[t]}`} aria-hidden />{TYPE_ICON[t]} {label(t)}{t === 'user' ? ' task' : t === 'system' ? ' task' : ''}
        </li>
      ))}
    </ul>
  );
}

function InstanceDetail({ id, defs }: { id: string; defs: Definition[] }) {
  const { data, isLoading, error } = useApi<History>(`/processes/${id}`);
  if (isLoading) return <Loading />;
  if (error || !data) return <ProblemBox error={error} />;
  const def = defs.find((d) => d.key === data.process);
  const href = docHref(data.business.type, data.business.ref, data.business.id);
  const active = data.path.find((p) => p.status === 'ACTIVE')?.step ?? (data.status === 'RUNNING' ? data.currentStep : null);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="rounded bg-[#0B1020] px-2 py-0.5 font-mono text-xs text-white">{data.flow}</span>
        <span className="font-semibold">{data.name}</span>
        <StatusChip status={data.status} />
      </div>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div><dt className="text-xs text-slate-500">Business object</dt>
          <dd className="font-medium">{label(data.business.type)} · {href ? <Link className="text-[#1A56DB] hover:underline" href={href}>{data.business.ref}</Link> : data.business.ref}</dd></div>
        <div><dt className="text-xs text-slate-500">Definition</dt><dd className="font-mono text-xs">{data.process} v{data.version}</dd></div>
        <div><dt className="text-xs text-slate-500">Started</dt><dd>{dateTime(data.startedAt)}</dd></div>
        <div><dt className="text-xs text-slate-500">Ended</dt><dd>{dateTime(data.endedAt)}</dd></div>
      </dl>
      {def && <Swimlane def={def} visited={new Set(data.path.map((p) => p.step))} active={active} />}
      <div>
        <h3 className="mb-2 text-sm font-semibold">Path</h3>
        <ol className="relative ml-3 border-l-2 border-slate-200">
          {data.path.map((s, i) => (
            <li key={`${s.step}-${i}`} className="mb-3 ml-5">
              <span className={`absolute -left-[9px] mt-1 h-4 w-4 rounded-full ring-4 ring-white ${s.status === 'ACTIVE' ? 'bg-amber-400' : s.status === 'SKIPPED' ? 'bg-slate-300' : 'bg-emerald-500'}`} aria-hidden />
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-mono text-xs text-slate-500">{s.step}</span>
                <span className="text-sm font-medium">{s.name}</span>
                <span className="text-xs text-slate-500">· {s.lane} · {s.type}</span>
                <StatusChip status={s.status === 'ACTIVE' ? 'ACTIVE_STEP' : s.status} />
              </div>
              {s.outcome && <p className="text-sm text-slate-700">{s.outcome}</p>}
              <p className="text-xs text-slate-500">{s.actor ?? '–'} · {dateTime(s.at)}</p>
            </li>
          ))}
        </ol>
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold">Human tasks</h3>
        {data.tasks.length === 0 ? <p className="text-sm text-slate-500">No human tasks were needed on this path.</p> : (
          <ul className="divide-y divide-slate-100 text-sm">
            {data.tasks.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                <span><span className="font-medium">{t.name}</span> <span className="text-xs text-slate-500">· {label(t.role)}</span>
                  {t.comment && <span className="block text-xs text-slate-600">“{t.comment}”</span>}</span>
                <span className="flex items-center gap-2"><StatusChip status={t.decision ?? t.status} /><span className="text-xs text-slate-500">{dateTime(t.completedAt)}</span></span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function ProcessMonitor() {
  const defs = useApi<Definition[]>('/process-definitions');
  const [flow, setFlow] = useState('');
  const [status, setStatus] = useState('RUNNING');
  const [open, setOpen] = useState<Instance | null>(null);
  const qs = new URLSearchParams();
  if (flow) qs.set('flow', flow);
  if (status) qs.set('status', status);
  const list = useList<Instance>(`/processes${qs.toString() ? `?${qs}` : ''}`);
  const definitions = defs.data ?? [];
  const shown = definitions.find((d) => d.flow === (flow || definitions[0]?.flow));

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="ADM-03 · Process monitor" title="Process monitor"
        subtitle="Where every business document sits in its BPMN flow (F1–F9): lanes, steps, gateways and the human tasks taken on the way." />

      <Card title="Process definitions" actions={<Legend />}>
        {defs.isLoading ? <Loading /> : defs.error ? <ProblemBox error={defs.error} /> : !definitions.length ? <Empty title="No process definitions deployed" /> : (
          <div className="space-y-4">
            <div role="tablist" aria-label="Flow" className="flex flex-wrap gap-1.5">
              {definitions.map((d) => {
                const selected = shown?.flow === d.flow;
                return (
                  <button key={d.key} role="tab" aria-selected={selected} type="button" onClick={() => setFlow(d.flow)} title={d.name}
                    className={`rounded-lg border px-2.5 py-1 text-xs font-medium ${selected ? 'border-[#1A56DB] bg-blue-50 text-[#1A56DB]' : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'}`}>
                    <span className="font-mono">{d.flow}</span> · {d.name.split(/[→(]/)[0].trim()}
                  </button>
                );
              })}
            </div>
            {shown && (
              <div>
                <p className="mb-2 text-sm"><span className="font-mono text-xs text-slate-500">{shown.key} v{shown.version}</span> · <span className="font-semibold">{shown.name}</span>
                  <span className="text-xs text-slate-500"> · {shown.steps.length} steps</span></p>
                <Swimlane def={shown} />
              </div>
            )}
          </div>
        )}
      </Card>

      <Card title="Process instances" actions={
        <div className="flex flex-wrap gap-2">
          <Select aria-label="Filter by flow" value={flow} onChange={(e) => setFlow(e.target.value)}
            options={[{ value: '', label: 'All flows' }, ...definitions.map((d) => ({ value: d.flow, label: `${d.flow} · ${d.name.split(/[→(]/)[0].trim()}` }))]} />
          <Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}
            options={STATUSES.map((s) => ({ value: s, label: s ? label(s) : 'All statuses' }))} />
        </div>
      }>
        <DataTable<Instance>
          rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
          loadingMore={list.isFetchingNextPage} empty={status === 'RUNNING' ? 'No running instances for this filter' : 'No process instances'}
          columns={[
            { key: 'process_key', header: 'Process', render: (r) => (
              <button type="button" onClick={() => setOpen(r)} className="font-mono text-xs font-medium text-[#1A56DB] hover:underline">{r.process_key}</button>
            ) },
            { key: 'business_ref', header: 'Business ref', render: (r) => <span><span className="font-medium">{r.business_ref}</span> <span className="text-xs text-slate-500">{label(r.business_type)}</span></span> },
            { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
            { key: 'current_step', header: 'Current step', render: (r) => <span className="font-mono text-xs">{r.current_step ?? '–'}</span> },
            { key: 'started_at', header: 'Started', render: (r) => dateTime(r.started_at) },
            { key: 'ended_at', header: 'Ended', render: (r) => dateTime(r.ended_at) },
          ]}
        />
      </Card>

      <Dialog open={!!open} title={open ? `${open.process_key} · ${open.business_ref}` : ''} onClose={() => setOpen(null)}>
        {open && <InstanceDetail id={open.id} defs={definitions} />}
      </Dialog>
    </div>
  );
}
