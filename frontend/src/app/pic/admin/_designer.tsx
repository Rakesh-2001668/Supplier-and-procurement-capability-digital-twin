'use client';

// Workflow designer (item 49): versioned process definitions. Pick a flow, see its versions and the BPMN diagram, start a draft from
// a version, edit the definition JSON (or import BPMN XML), validate (reachability, gateway outcomes, roles, task-kind handlers),
// publish a new version and compare versions. Running instances finish on the version they started on.

import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { ProcessDiagram } from '@/components/pic/bpmn-viewer';
import { api } from '@/lib/pic/api';
import { dateTime } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Step = { id: string; type: string; lane: string; name: string; screen?: string | null; taskKind?: string; roles?: string[]; slaBusinessDays?: number };
type Flow = { from: string; to: string; label?: string };
type Version = { key: string; flow: string; version: number; name: string; status: string; scope: string; baseVersion: number | null; note: string | null;
  revision: number; publishedAt: string | null; editable: boolean; steps: Step[]; flows: Flow[]; lanes: string[]; branches: string | null };
type VersionRow = Omit<Version, 'steps' | 'flows'> & { steps: number; flows: number };
type Validation = { valid: boolean; errors: { code: string; message: string; step?: string }[]; warnings: { code: string; message: string; step?: string }[] };
type Diff = { from: number; to: number; identical: boolean; stepsAdded: Step[]; stepsRemoved: Step[]; flowsAdded: Flow[]; flowsRemoved: Flow[];
  stepsChanged: { id: string; fields: { field: string; from: unknown; to: unknown }[] }[] };

function Report({ v }: { v: Validation }) {
  return (
    <div className="space-y-2" aria-live="polite">
      <p className={`text-sm font-semibold ${v.valid ? 'text-emerald-700' : 'text-red-700'}`}>
        {v.valid ? 'Valid: every step is reachable, gateways have both outcomes, roles and task kinds exist.' : `${v.errors.length} problem(s) to fix before publishing`}
      </p>
      {v.errors.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-sm text-red-800">{v.errors.map((e, i) => <li key={i}><span className="font-mono text-xs">{e.code}</span> {e.message}</li>)}</ul>
      )}
      {v.warnings.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-xs text-amber-800">{v.warnings.map((e, i) => <li key={i}>{e.message}</li>)}</ul>
      )}
    </div>
  );
}

function DiffView({ d }: { d: Diff }) {
  if (d.identical) return <p className="text-sm text-slate-600">Versions {d.from} and {d.to} are identical.</p>;
  return (
    <div className="space-y-2 text-sm">
      {d.stepsAdded.length > 0 && <p><span className="font-semibold text-emerald-700">Added steps: </span>{d.stepsAdded.map((s) => `${s.id} ${s.name}`).join('; ')}</p>}
      {d.stepsRemoved.length > 0 && <p><span className="font-semibold text-red-700">Removed steps: </span>{d.stepsRemoved.map((s) => `${s.id} ${s.name}`).join('; ')}</p>}
      {d.stepsChanged.map((c) => (
        <p key={c.id}><span className="font-semibold">{c.id}: </span>{c.fields.map((f) => `${f.field} ${JSON.stringify(f.from)} → ${JSON.stringify(f.to)}`).join(', ')}</p>
      ))}
      {d.flowsAdded.length > 0 && <p><span className="font-semibold text-emerald-700">Added flows: </span>{d.flowsAdded.map((f) => `${f.from}→${f.to}${f.label ? ` (${f.label})` : ''}`).join(', ')}</p>}
      {d.flowsRemoved.length > 0 && <p><span className="font-semibold text-red-700">Removed flows: </span>{d.flowsRemoved.map((f) => `${f.from}→${f.to}${f.label ? ` (${f.label})` : ''}`).join(', ')}</p>}
    </div>
  );
}

function Editor({ v, onDone }: { v: Version; onDone: () => void }) {
  const initial = JSON.stringify({ steps: v.steps, flows: v.flows, lanes: v.lanes, branches: v.branches }, null, 2);
  const [text, setText] = useState(initial);
  const [problem, setProblem] = useState<string | null>(null);
  const [report, setReport] = useState<Validation | null>(null);
  const [xml, setXml] = useState('');
  const [importOpen, setImportOpen] = useState(false);
  const path = `/process-definitions/${v.key}/versions/${v.version}`;

  function parsed(): unknown | null {
    try { setProblem(null); return JSON.parse(text); } catch (e) { setProblem(`Not valid JSON: ${(e as Error).message}`); return null; }
  }
  const save = useCommand(() => api.put<Version>(path, { definition: parsed() }, { ifMatch: `"${v.revision}"` }), { success: 'Draft saved', onSuccess: onDone });
  const check = useCommand((definition: unknown) => api.post<Validation>('/process-definitions/validate', { key: v.key, definition }, { idempotencyKey: false }),
    { onSuccess: setReport });
  const publish = useCommand(() => api.post<Version>(`${path}/publish`, {}), { success: (r) => `Version ${r.version} published: new instances start on it`, onSuccess: onDone });
  const discard = useCommand(() => api.delete(path), { success: 'Draft discarded', onSuccess: onDone });
  const importBpmn = useCommand((body: string) => api.post<{ definition: unknown }>('/process-definitions/bpmn/parse', { xml: body }), {
    success: 'BPMN imported into the editor; review, then save', onSuccess: (r) => { setText(JSON.stringify({ ...JSON.parse(initial), ...(r.definition as object) }, null, 2)); setImportOpen(false); },
  });

  return (
    <Card title={`Edit draft v${v.version} (based on v${v.baseVersion ?? '–'})`} actions={
      <div className="flex gap-2">
        <Button onClick={() => setImportOpen(true)}>Import BPMN</Button>
        <Button variant="danger" busy={discard.isPending} onClick={() => discard.mutate()}>Discard</Button>
      </div>
    }>
      <p className="mb-2 text-xs text-slate-600">
        Steps carry id, type (event, user, system, gateway), lane, name and optionally taskKind, roles and slaBusinessDays. Flows connect steps; a gateway needs
        one flow labelled yes and one labelled no. Steps the services drive by id (the shipped ones) cannot be removed.
      </p>
      <Field label="Definition (JSON)" error={problem ?? undefined}>{(id, described) => (
        <Textarea id={id} aria-describedby={described} rows={18} className="font-mono text-xs" spellCheck={false} value={text} onChange={(e) => setText(e.target.value)} />
      )}</Field>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button onClick={() => { const d = parsed(); if (d) check.mutate(d); }} busy={check.isPending}>Validate</Button>
        <Button variant="primary" busy={save.isPending} onClick={() => { if (parsed()) save.mutate(); }}>Save draft</Button>
        <Button variant="primary" busy={publish.isPending} disabled={text !== initial} title={text !== initial ? 'Save the draft first' : undefined}
          onClick={() => publish.mutate()}>Publish</Button>
      </div>
      {report && <div className="mt-3"><Report v={report} /></div>}
      <ProblemBox error={publish.error ?? save.error} />
      <Dialog open={importOpen} title="Import BPMN 2.0 XML" onClose={() => setImportOpen(false)}>
        <Field label="BPMN XML">{(id) => <Textarea id={id} rows={12} className="font-mono text-xs" value={xml} onChange={(e) => setXml(e.target.value)} />}</Field>
        <div className="mt-3 flex justify-end"><Button variant="primary" busy={importBpmn.isPending} disabled={xml.trim().length < 10} onClick={() => importBpmn.mutate(xml)}>Read diagram</Button></div>
        <ProblemBox error={importBpmn.error} />
      </Dialog>
    </Card>
  );
}

function VersionView({ processKey, version, onChange }: { processKey: string; version: number; onChange: () => void }) {
  const { data, isLoading, error } = useApi<Version>(`/process-definitions/${processKey}/versions/${version}`);
  const [selected, setSelected] = useState<string | null>(null);
  const validate = useCommand(() => api.post<Validation>(`/process-definitions/${processKey}/versions/${version}/validate`, {}, { idempotencyKey: false }), {});
  if (isLoading) return <Loading />;
  if (error || !data) return <ProblemBox error={error} />;
  const step = data.steps.find((s) => s.id === selected);
  return (
    <div className="space-y-4">
      <Card title={`${data.name} · v${data.version}`} actions={<StatusChip status={data.status} />}>
        <ProcessDiagram processKey={processKey} version={version} selected={selected} onSelect={setSelected} height={420} />
        {step && (
          <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            <div><dt className="text-xs text-slate-500">Step</dt><dd className="font-mono">{step.id}</dd></div>
            <div><dt className="text-xs text-slate-500">Name</dt><dd>{step.name}</dd></div>
            <div><dt className="text-xs text-slate-500">Lane · type</dt><dd>{step.lane} · {step.type}</dd></div>
            <div><dt className="text-xs text-slate-500">Task kind · SLA</dt><dd>{step.taskKind ?? '–'} · {step.slaBusinessDays ? `${step.slaBusinessDays} days` : 'rule'}</dd></div>
          </dl>
        )}
        <div className="mt-3 flex gap-2">
          <Button busy={validate.isPending} onClick={() => validate.mutate()}>Validate this version</Button>
        </div>
        {validate.data && <div className="mt-3"><Report v={validate.data} /></div>}
      </Card>
      {data.editable && <Editor key={`${data.version}-${data.revision}`} v={data} onDone={onChange} />}
    </div>
  );
}

export function WorkflowTab() {
  const defs = useApi<{ key: string; flow: string; version: number; name: string; status: string }[]>('/process-definitions');
  const [key, setKey] = useState('');
  const [version, setVersion] = useState<number | null>(null);
  const [compare, setCompare] = useState<[number, number] | null>(null);
  const current = key || defs.data?.[0]?.key || '';
  const versions = useApi<VersionRow[]>(current ? `/process-definitions/${current}/versions` : null);
  const diff = useApi<Diff>(compare && current ? `/process-definitions/${current}/diff?from=${compare[0]}&to=${compare[1]}` : null);
  const draft = useCommand((base: number) => api.post<Version>(`/process-definitions/${current}/drafts`, { baseVersion: base }), {
    success: (r) => `Draft v${r.version} created`, onSuccess: (r) => setVersion(r.version),
  });
  if (defs.isLoading) return <Loading />;
  if (defs.error || !defs.data) return <ProblemBox error={defs.error} />;
  const rows = (versions.data ?? []) as unknown as (VersionRow & Record<string, unknown>)[];
  const shown = version ?? rows.filter((r) => r.status === 'ACTIVE').at(-1)?.version ?? rows.at(-1)?.version ?? null;
  const active = rows.filter((r) => r.status === 'ACTIVE').at(-1);
  return (
    <div className="space-y-4">
      <Card title="Workflow definitions (versioned)">
        <p className="mb-3 text-sm text-slate-600">
          The nine shipped flows are version 1. Start a draft from any version, edit and validate it, then publish: new documents follow the new version,
          documents already in flight finish on the version they started on.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Flow">{(id) => (
            <Select id={id} value={current} onChange={(e) => { setKey(e.target.value); setVersion(null); setCompare(null); }}
              options={defs.data!.map((d) => ({ value: d.key, label: `${d.flow} · ${d.name}` }))} />
          )}</Field>
        </div>
        <div className="mt-3">
          <DataTable<VersionRow & Record<string, unknown>> rows={rows} loading={versions.isLoading} error={versions.error} empty="No versions" columns={[
            { key: 'version', header: 'Version', render: (r) => <button className="font-mono text-[#1A56DB] hover:underline" onClick={() => setVersion(r.version)}>v{r.version}</button> },
            { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
            { key: 'scope', header: 'Owner', render: (r) => (r.scope === 'SHARED' ? 'Shared baseline' : 'This tenant') },
            { key: 'steps', header: 'Steps / flows', render: (r) => `${r.steps} / ${r.flows}` },
            { key: 'publishedAt', header: 'Published', render: (r) => (r.publishedAt ? dateTime(r.publishedAt) : '–') },
            { key: 'note', header: 'Note', render: (r) => r.note ?? '–' },
            { key: 'actions', header: '', render: (r) => (
              <span className="flex gap-2">
                <Button busy={draft.isPending} onClick={() => draft.mutate(r.version)}>New draft from v{r.version}</Button>
                {active && active.version !== r.version && <Button onClick={() => setCompare([Math.min(r.version, active.version), Math.max(r.version, active.version)])}>Compare with v{active.version}</Button>}
              </span>
            ) },
          ]} />
        </div>
        <ProblemBox error={draft.error} />
      </Card>
      {compare && (
        <Card title={`Changes v${compare[0]} → v${compare[1]}`} actions={<Button variant="ghost" onClick={() => setCompare(null)}>Close</Button>}>
          {diff.isLoading ? <Loading /> : diff.error || !diff.data ? <ProblemBox error={diff.error} /> : <DiffView d={diff.data} />}
        </Card>
      )}
      {current && shown !== null && (
        <VersionView key={`${current}-${shown}`} processKey={current} version={shown} onChange={() => { setVersion(null); void versions.refetch(); }} />
      )}
    </div>
  );
}
