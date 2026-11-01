'use client';

import { useState } from 'react';
import { Button, Card, DataTable, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { useSessionUser } from '../invoices/_components';

type Catalogue = Record<string, { label: string; header: string[]; lines: string[] }>;
type Documents = Record<string, { header: string[]; lines: string[] }>;
type Version = { version: string; effectiveFrom: string; effectiveTo: string | null; scope: Record<string, string>; body: { documents: Documents }; description: string | null };
type State = { catalogue: Catalogue; versions: Version[]; effective: { documents: Documents } };
type Sim = { result: { decision: string; missingFields: string[]; reasons: string[] }; resolved: { ref: string }; compare?: { changed: boolean; draft: { result: { decision: string; missingFields: string[] } } } };

const SCOPES: [string, string][] = [['companyCode', 'Company code'], ['plant', 'Plant'], ['category', 'Category'], ['purchaseType', 'Purchase type'], ['supplierGroup', 'Supplier group']];

/** TD §6 / P14 rule MANDATORY-FIELDS: which fields each document must carry before it is submitted, released, posted, captured or registered. */
export function MandatoryFieldsTab() {
  const user = useSessionUser();
  const admin = !!user?.roles.includes('TENANT_ADMIN');
  const state = useApi<State>('/admin/mandatory-fields');
  const [picked, setPicked] = useState<Documents | null>(null);
  const [scope, setScope] = useState<Record<string, string>>({});
  const [from, setFrom] = useState('');
  const [reason, setReason] = useState('');
  const save = useCommand(() => api.post<Version>('/admin/mandatory-fields', {
    documents: picked, effectiveFrom: from || undefined, reason: reason.trim(), ...Object.fromEntries(Object.entries(scope).filter(([, v]) => v.trim()).map(([k, v]) => [k, v.trim()])),
  }), { success: (r) => `Mandatory fields saved as version ${r.version}`, onSuccess: () => { setPicked(null); setReason(''); } });
  if (state.isLoading) return <Loading />;
  if (state.error) return <ProblemBox error={state.error} />;
  const s = state.data!;
  const docs: Documents = picked ?? s.effective.documents;
  const toggle = (doc: string, part: 'header' | 'lines', field: string) => {
    const current = docs[doc] ?? { header: [], lines: [] };
    const list = current[part].includes(field) ? current[part].filter((f) => f !== field) : [...current[part], field];
    setPicked({ ...docs, [doc]: { ...current, [part]: list } });
  };
  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-600">
        A document missing a mandatory field is refused with the list of missing fields: requisition at submit, purchase order at release, goods receipt at
        posting, invoice at capture, supplier at registration. A version scoped to a company code, plant, category, purchase type or supplier group replaces
        the default for that scope. Versions are effective-dated and never edited.
      </p>
      <Card title={picked ? 'Draft version (not saved)' : 'Fields in force by default'}>
        <div className="space-y-4">
          {Object.entries(s.catalogue).map(([doc, spec]) => (
            <fieldset key={doc} className="rounded-lg border border-slate-200 p-3">
              <legend className="px-1 text-sm font-semibold">{spec.label}</legend>
              {(['header', 'lines'] as const).map((part) => spec[part].length > 0 && (
                <div key={part} className="mb-1">
                  <p className="text-xs uppercase tracking-wide text-slate-500">{part === 'header' ? 'Document fields' : 'Line fields'}</p>
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    {spec[part].map((f) => (
                      <label key={f} className="flex items-center gap-1.5 text-sm">
                        <input type="checkbox" disabled={!admin} checked={(docs[doc]?.[part] ?? []).includes(f)} onChange={() => toggle(doc, part, f)} />
                        {label(f)}
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </fieldset>
          ))}
        </div>
        {admin && (
          <div className="mt-4 space-y-3">
            <div className="grid gap-3 md:grid-cols-6">
              {SCOPES.map(([key, name]) => (
                <Field key={key} label={name} hint={key === 'companyCode' ? 'Empty = every' : undefined}>{(id) => (
                  <Input id={id} value={scope[key] ?? ''} onChange={(e) => setScope((v) => ({ ...v, [key]: e.target.value }))} />
                )}</Field>
              ))}
              <Field label="Effective from">{(id) => <Input id={id} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
            </div>
            <Field label="Reason (required)">{(id) => <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
            <div className="flex justify-end gap-2">
              {picked && <Button onClick={() => setPicked(null)}>Discard</Button>}
              <Button variant="primary" busy={save.isPending} disabled={!picked || reason.trim().length < 3} onClick={() => save.mutate()}>Save as new version</Button>
            </div>
          </div>
        )}
      </Card>
      <Card title="Versions">
        <DataTable<Version & { id: string }> rows={s.versions.map((v) => ({ ...v, id: v.version }))} empty="No versions" columns={[
          { key: 'version', header: 'Version' },
          { key: 'effectiveFrom', header: 'Effective', render: (v) => date(v.effectiveFrom) },
          { key: 'scope', header: 'Scope', render: (v) => Object.keys(v.scope).length ? Object.entries(v.scope).map(([k, x]) => `${label(k)} ${x}`).join(', ') : <StatusChip status="DEFAULT" /> },
          { key: 'fields', header: 'Mandatory fields', render: (v) => Object.entries(v.body.documents).map(([d, f]) => `${label(d)}: ${[...f.header, ...f.lines.map((x) => `line ${x}`)].join(', ') || 'none'}`).join(' · ') },
        ]} />
      </Card>
      <SimulateCard catalogue={s.catalogue} draft={picked} />
    </div>
  );
}

function SimulateCard({ catalogue, draft }: { catalogue: Catalogue; draft: Documents | null }) {
  const [doc, setDoc] = useState('REQUISITION');
  const [header, setHeader] = useState('{"purpose_code": "MAINTENANCE"}');
  const [lines, setLines] = useState('[{"description": "Clamp kit", "qty": 1}]');
  const [scope, setScope] = useState({ plant: '', category: '', purchaseType: '', supplierGroup: '' });
  const [parseError, setParseError] = useState<string | null>(null);
  const run = useCommand(async () => {
    let h: unknown;
    let l: unknown;
    try {
      h = JSON.parse(header || '{}');
      l = JSON.parse(lines || '[]');
    } catch (e) {
      throw new Error(`Header and lines must be valid JSON: ${(e as Error).message}`);
    }
    return api.post<Sim>('/admin/rules/simulate', {
      key: 'MANDATORY-FIELDS', inputs: { document: doc, header: h, lines: l }, scope: Object.fromEntries(Object.entries(scope).filter(([, v]) => v.trim())),
      draftBody: draft ? { documents: draft } : undefined,
    });
  }, { onSuccess: () => setParseError(null) });
  return (
    <Card title="Simulate a document (ADM-03)">
      <div className="grid gap-3 md:grid-cols-5">
        <Field label="Document">{(id) => <Select id={id} value={doc} onChange={(e) => setDoc(e.target.value)} options={Object.entries(catalogue).map(([k, v]) => ({ value: k, label: v.label }))} />}</Field>
        {(['plant', 'category', 'purchaseType', 'supplierGroup'] as const).map((k) => (
          <Field key={k} label={label(k)}>{(id) => <Input id={id} value={scope[k]} onChange={(e) => setScope((v) => ({ ...v, [k]: e.target.value }))} />}</Field>
        ))}
        <div className="md:col-span-2"><Field label="Document fields (JSON)">{(id) => <Textarea id={id} className="font-mono text-xs" value={header} onChange={(e) => setHeader(e.target.value)} />}</Field></div>
        <div className="md:col-span-3"><Field label="Lines (JSON array)">{(id) => <Textarea id={id} className="font-mono text-xs" value={lines} onChange={(e) => setLines(e.target.value)} />}</Field></div>
      </div>
      <div className="mt-3 flex justify-end"><Button variant="primary" busy={run.isPending} onClick={() => { setParseError(null); run.mutate(undefined, { onError: (e) => setParseError(e.message) }); }}>Simulate</Button></div>
      {parseError && <p role="alert" className="mt-2 text-sm text-red-700">{parseError}</p>}
      {run.data && (
        <div className="mt-3 space-y-1 text-sm" role="status">
          <p><StatusChip status={run.data.result.decision === 'ACCEPTED' ? 'OK' : 'FAILED'} /> {run.data.result.reasons.join('; ')} <span className="font-mono text-xs text-slate-500">({run.data.resolved.ref})</span></p>
          {run.data.compare && <p className="text-slate-700">Draft: {run.data.compare.draft.result.decision.toLowerCase()}{run.data.compare.draft.result.missingFields.length ? ` — missing ${run.data.compare.draft.result.missingFields.join(', ')}` : ''}</p>}
        </div>
      )}
    </Card>
  );
}
