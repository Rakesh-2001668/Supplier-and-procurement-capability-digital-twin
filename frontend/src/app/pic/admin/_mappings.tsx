'use client';

// ERP field mappings (item 50): per target system and message type, versioned rules (rename, copy, constant, drop, format, lookup)
// applied to the outbound payload before the connector. Test a draft against a sample payload (a real message of that type when one
// exists) before publishing. Without an active mapping the payload goes out exactly as the services build it.

import { useState } from 'react';
import { Button, Card, DataTable, Field, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Mapping = { id: string; targetSystem: string; messageType: string; version: number; status: string; rules: unknown[]; note: string | null;
  publishedAt: string | null; rowVersion: number };
type Catalog = { targetSystems: string[]; messageTypes: { type: string; samples: Record<string, unknown> }[]; ops: string[]; formatKinds: string[] };
type Preview = { valid: boolean; problems: { rule: number | null; message: string }[]; outbound: unknown; changes: { path: string; change: string; before: unknown; after: unknown }[];
  sample: unknown };

const EXAMPLE = `[
  { "op": "rename", "from": "grossMinor", "to": "GrossAmountPaise" },
  { "op": "constant", "to": "SourceSystem", "value": "PIC" },
  { "op": "format", "field": "invoiceDate", "kind": "date", "pattern": "%d.%m.%Y" },
  { "op": "lookup", "field": "companyCode", "table": { "1000": "AXN1" } }
]`;

export function MappingsTab() {
  const catalog = useApi<Catalog>('/admin/field-mappings/catalog');
  const [target, setTarget] = useState('');
  const [type, setType] = useState('');
  const system = target || catalog.data?.targetSystems[0] || '';
  const mtype = type || catalog.data?.messageTypes[0]?.type || '';
  const list = useApi<Mapping[]>(system && mtype ? `/admin/field-mappings?targetSystem=${system}&messageType=${mtype}` : null);
  const [rules, setRules] = useState(EXAMPLE);
  const [sample, setSample] = useState('');
  const [note, setNote] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const [editing, setEditing] = useState<Mapping | null>(null);

  const sampleFor = catalog.data?.messageTypes.find((m) => m.type === mtype)?.samples[system];

  function parse(text: string, what: string): unknown | null {
    try { return JSON.parse(text); } catch (e) { setProblem(`${what} is not valid JSON: ${(e as Error).message}`); return null; }
  }
  const preview = useCommand(() => {
    const r = parse(rules, 'Rules');
    const s = sample.trim() ? parse(sample, 'Sample payload') : undefined;
    if (r === null || (sample.trim() && s === null)) return Promise.reject(new Error('Fix the JSON first'));
    setProblem(null);
    return api.post<Preview>('/admin/field-mappings/preview', { rules: r, samplePayload: s, targetSystem: system, messageType: mtype }, { idempotencyKey: false });
  }, {});
  const save = useCommand(() => {
    const r = parse(rules, 'Rules');
    if (r === null) return Promise.reject(new Error('Fix the JSON first'));
    setProblem(null);
    return editing
      ? api.put<Mapping>(`/admin/field-mappings/${editing.id}`, { rules: r, note: note || undefined }, { ifMatch: `"${editing.rowVersion}"` })
      : api.post<Mapping>('/admin/field-mappings', { targetSystem: system, messageType: mtype, rules: r, note: note || undefined });
  }, { success: (m) => `Draft version ${m.version} saved`, onSuccess: () => setEditing(null) });
  const publish = useCommand((id: string) => api.post<Mapping>(`/admin/field-mappings/${id}/publish`, {}), { success: (m) => `Version ${m.version} is now in use` });
  const retire = useCommand((id: string) => api.post<Mapping>(`/admin/field-mappings/${id}/retire`, { reason: 'Switched off from the mapping screen' }),
    { success: 'Mapping switched off: messages go out unmapped again' });
  const discard = useCommand((id: string) => api.delete(`/admin/field-mappings/${id}`), { success: 'Draft deleted' });

  if (catalog.isLoading) return <Loading />;
  if (catalog.error || !catalog.data) return <ProblemBox error={catalog.error} />;
  return (
    <div className="space-y-4">
      <Card title="ERP field mappings">
        <p className="mb-3 text-sm text-slate-600">Rules run in order on a copy of the outbound payload. The stored message keeps the canonical payload; what was sent
          (and the mapping version) is recorded on the integration message. Paths are dotted; <code>lines[].qty</code> addresses every line.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Target system">{(id) => <Select id={id} value={system} onChange={(e) => setTarget(e.target.value)} options={catalog.data!.targetSystems.map((t) => ({ value: t, label: t }))} />}</Field>
          <Field label="Message type">{(id) => <Select id={id} value={mtype} onChange={(e) => setType(e.target.value)} options={catalog.data!.messageTypes.map((m) => ({ value: m.type, label: m.type }))} />}</Field>
        </div>
        <div className="mt-3">
          <DataTable<Mapping & Record<string, unknown>> rows={(list.data ?? []) as (Mapping & Record<string, unknown>)[]} loading={list.isLoading} error={list.error}
            empty="No mapping yet: payloads go out as built" columns={[
              { key: 'version', header: 'Version', render: (r) => <span className="font-mono">v{r.version}</span> },
              { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
              { key: 'rules', header: 'Rules', render: (r) => r.rules.length },
              { key: 'publishedAt', header: 'In use since', render: (r) => (r.publishedAt ? dateTime(r.publishedAt) : '–') },
              { key: 'note', header: 'Note', render: (r) => r.note ?? '–' },
              { key: 'actions', header: '', render: (r) => (
                <span className="flex gap-2">
                  <Button onClick={() => { setRules(JSON.stringify(r.rules, null, 2)); setNote(r.note ?? ''); setEditing(r.status === 'DRAFT' ? r : null); }}>
                    {r.status === 'DRAFT' ? 'Edit' : 'Copy to editor'}</Button>
                  {r.status === 'DRAFT' && <Button variant="primary" busy={publish.isPending} onClick={() => publish.mutate(r.id)}>Publish</Button>}
                  {r.status === 'DRAFT' && <Button variant="danger" onClick={() => discard.mutate(r.id)}>Delete</Button>}
                  {r.status === 'ACTIVE' && <Button variant="danger" busy={retire.isPending} onClick={() => retire.mutate(r.id)}>Switch off</Button>}
                </span>
              ) },
            ]} />
        </div>
      </Card>
      <Card title={editing ? `Edit draft v${editing.version}` : 'New draft version'}>
        <div className="grid gap-3 lg:grid-cols-2">
          <Field label="Rules (JSON list)" hint={`Operations: ${catalog.data.ops.join(', ')}. Format kinds: ${catalog.data.formatKinds.join(', ')}`}>{(id, d) => (
            <Textarea id={id} aria-describedby={d} rows={14} className="font-mono text-xs" spellCheck={false} value={rules} onChange={(e) => setRules(e.target.value)} />
          )}</Field>
          <Field label="Sample payload (JSON)" hint={sampleFor ? 'Empty: the latest real message of this type is used' : 'No real message of this type yet: paste a sample'}>{(id, d) => (
            <Textarea id={id} aria-describedby={d} rows={14} className="font-mono text-xs" spellCheck={false} value={sample} onChange={(e) => setSample(e.target.value)}
              placeholder={sampleFor ? JSON.stringify(sampleFor, null, 2).slice(0, 600) : '{ "invoiceNo": "INV-1", "grossMinor": 118000 }'} />
          )}</Field>
        </div>
        <Field label="Note">{(id) => <textarea id={id} rows={1} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button busy={preview.isPending} onClick={() => preview.mutate()}>Test with sample</Button>
          <Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>{editing ? 'Save draft' : 'Save as new draft'}</Button>
          {editing && <Button variant="ghost" onClick={() => setEditing(null)}>Cancel edit</Button>}
        </div>
        {problem && <p role="alert" className="mt-2 text-sm text-red-700">{problem}</p>}
        <ProblemBox error={preview.error ?? save.error ?? publish.error} />
        {preview.data && (
          <div className="mt-4 space-y-2" aria-live="polite">
            {!preview.data.valid ? (
              <ul className="list-disc pl-5 text-sm text-red-800">{preview.data.problems.map((p, i) => <li key={i}>{p.rule !== null ? `Rule ${p.rule + 1}: ` : ''}{p.message}</li>)}</ul>
            ) : (
              <>
                <p className="text-sm font-semibold text-emerald-700">{preview.data.changes.length} change(s) to the payload</p>
                <ul className="space-y-0.5 text-xs">
                  {preview.data.changes.map((c) => (
                    <li key={c.path} className="font-mono"><span className="font-semibold">{c.change}</span> {c.path}: {JSON.stringify(c.before)} → {JSON.stringify(c.after)}</li>
                  ))}
                </ul>
                <pre className="max-h-72 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">{JSON.stringify(preview.data.outbound, null, 2)}</pre>
              </>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
