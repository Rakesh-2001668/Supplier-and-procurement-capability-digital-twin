'use client';

// ADM-03 approval-matrix simulation: pick a rule, enter document facts, see the effective rule version, the approver chain or
// decision and why. Optional compare mode evaluates an unsaved draft body next to the current version. Nothing is saved.

import { FormEvent, useState } from 'react';
import { Button, Card, Field, Input, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { label } from '@/lib/pic/format';
import { useCommand } from '@/lib/pic/hooks';

type FieldSpec = { name: string; label: string; kind: 'money' | 'number' | 'text' | 'bool' | 'select' | 'list'; options?: string[]; hint?: string };

const RULES: Record<string, { title: string; fields: FieldSpec[] }> = {
  'DMN-01': { title: 'Requisition approval route', fields: [
    { name: 'valueMinor', label: 'Requisition value (₹)', kind: 'money' },
    { name: 'channel', label: 'Channel', kind: 'select', options: ['OTHER', 'CATALOGUE', 'CONTRACT'] },
    { name: 'accountType', label: 'Account assignment', kind: 'select', options: ['', 'COST_CENTER', 'WBS', 'ORDER', 'ASSET'] },
    { name: 'purchaseType', label: 'Purchase type', kind: 'select', options: ['STOCK', 'NON_STOCK', 'SERVICE', 'EXPENSE', 'ASSET', 'CONSIGNMENT', 'SUBCONTRACTING'] },
  ] },
  'PO-APPROVAL': { title: 'PO approval strategy', fields: [
    { name: 'valueMinor', label: 'PO value (₹)', kind: 'money' },
    { name: 'priceDeviation', label: 'Price outside contract tolerance', kind: 'bool' },
  ] },
  'AWARD-APPROVAL': { title: 'Sourcing award approval', fields: [
    { name: 'annualValueMinor', label: 'Annual award value (₹)', kind: 'money' },
    { name: 'notLowest', label: 'Award is not to the lowest bid', kind: 'bool' },
  ] },
  'CONTRACT-APPROVAL': { title: 'Contract approval', fields: [
    { name: 'valueMinor', label: 'Contract target value (₹)', kind: 'money' },
    { name: 'nonStandardClause', label: 'Contains a non-standard clause', kind: 'bool' },
  ] },
  'CONTRACT-AMENDMENT': { title: 'Contract amendment / termination', fields: [
    { name: 'kind', label: 'Amendment kind', kind: 'select', options: ['VARIATION', 'EXTENSION', 'TERMS', 'TERMINATION'] },
    { name: 'valueDeltaMinor', label: 'Value change (₹, negative for a reduction)', kind: 'money' },
  ] },
  'DMN-02': { title: 'Touchless PO (with PO risk score)', fields: [
    { name: 'valueMinor', label: 'PO value (₹)', kind: 'money' },
    { name: 'supplierStatus', label: 'Supplier status for the category', kind: 'select', options: ['QUALIFIED', 'PREFERRED', 'APPROVED', 'NEW', 'BLOCKED'] },
    { name: 'priceSources', label: 'Price sources (comma-separated)', kind: 'list', hint: 'CONTRACT, CATALOGUE, INFO_RECORD, MANUAL' },
    { name: 'lateProb', label: 'Late-delivery probability (0–1)', kind: 'number' },
    { name: 'priceDeviation', label: 'Price deviation', kind: 'bool' },
    { name: 'splitPattern', label: 'Split pattern detected', kind: 'bool' },
    { name: 'accountChanged', label: 'Account assignment changed from the requisition', kind: 'bool' },
  ] },
  'DMN-03': { title: 'Invoice match tolerances', fields: [
    { name: 'poUnitPriceMinor', label: 'PO unit price (₹)', kind: 'money' },
    { name: 'invoiceUnitPriceMinor', label: 'Invoice unit price (₹)', kind: 'money' },
    { name: 'availableQty', label: 'Quantity available to invoice', kind: 'number' },
    { name: 'invoicedQty', label: 'Quantity billed', kind: 'number' },
  ] },
};

const DEFAULTS: Record<string, string> = {
  valueMinor: '150000', annualValueMinor: '6000000', valueDeltaMinor: '0', channel: 'OTHER', purchaseType: 'STOCK', kind: 'VARIATION',
  supplierStatus: 'QUALIFIED', priceSources: 'CONTRACT', lateProb: '0.05', poUnitPriceMinor: '1000', invoiceUnitPriceMinor: '1005',
  availableQty: '100', invoicedQty: '100',
};

type Candidate = { version: string; effectiveFrom: string; effectiveTo: string | null; scope: Record<string, string>; specificity: number;
  applies: boolean; excludedBecause: string[] };
type Decision = { chain?: string[]; decision?: string; reasons?: string[]; band?: number | string; [key: string]: unknown };
type SimResult = {
  key: string; on: string; resolved: { ref: string; version: string; body: unknown; why: string }; candidates: Candidate[]; result: Decision;
  compare?: { draft: { ref: string; result: Decision }; changed: boolean; changedFields: string[] };
};

function toInputs(key: string, values: Record<string, string>, flags: Record<string, boolean>) {
  const inputs: Record<string, unknown> = {};
  for (const f of RULES[key].fields) {
    if (f.kind === 'bool') { inputs[f.name] = !!flags[f.name]; continue; }
    const raw = (values[f.name] ?? '').trim();
    if (raw === '') continue;
    if (f.kind === 'money') inputs[f.name] = Math.round(Number(raw) * 100);
    else if (f.kind === 'list') inputs[f.name] = raw.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
    else inputs[f.name] = raw;
  }
  return inputs;
}

function Outcome({ title, d }: { title: string; d: Decision }) {
  const chain = d.chain ?? [];
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</p>
      {d.decision && <p className="mt-1"><StatusChip status={d.decision} /></p>}
      {'chain' in d && (
        chain.length ? (
          <ol className="mt-2 flex flex-wrap items-center gap-1 text-sm" aria-label="Approver chain">
            {chain.map((role, i) => (
              <li key={`${role}-${i}`} className="flex items-center gap-1">
                {i > 0 && <span aria-hidden className="text-slate-400">→</span>}
                <span className="rounded bg-[#1A56DB]/10 px-2 py-0.5 font-medium text-[#1A56DB]">{label(role)}</span>
              </li>
            ))}
          </ol>
        ) : <p className="mt-2 text-sm font-medium text-emerald-700">No approval needed (auto-approved)</p>
      )}
      {d.reasons && d.reasons.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-slate-700">{d.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      )}
      {typeof d.riskScore === 'number' && <p className="mt-1 text-xs text-slate-600">PO risk score {d.riskScore}/100</p>}
      {typeof d.note === 'string' && <p className="mt-1 text-xs text-slate-500">{d.note}</p>}
    </div>
  );
}

export function SimulationTab() {
  const [key, setKey] = useState('DMN-01');
  const [values, setValues] = useState<Record<string, string>>(DEFAULTS);
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [on, setOn] = useState('');
  const [scope, setScope] = useState({ companyCode: '', plant: '', category: '', purchaseType: '' });
  const [draft, setDraft] = useState('');
  const [invalid, setInvalid] = useState<string | null>(null);
  const [result, setResult] = useState<SimResult | null>(null);
  const run = useCommand((body: Record<string, unknown>) => api.post<SimResult>('/admin/rules/simulate', body, { idempotencyKey: false }), {
    onSuccess: setResult,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    let draftBody: unknown;
    if (draft.trim()) {
      try { draftBody = JSON.parse(draft); } catch (err) { setInvalid(`Draft body is not valid JSON: ${(err as Error).message}`); return; }
    }
    setInvalid(null);
    const cleanScope = Object.fromEntries(Object.entries(scope).filter(([, v]) => v.trim()).map(([k, v]) => [k, v.trim()]));
    run.mutate({ key, inputs: toInputs(key, values, flags), on: on || undefined,
      scope: Object.keys(cleanScope).length ? cleanScope : undefined, draftBody });
  }

  return (
    <Card title="Approval-matrix simulation (ADM-03)">
      <p className="mb-3 text-sm text-slate-600">See which rule version applies to a document and who would approve it, using the same decision
        logic as the live workflows. Paste a draft body to compare a planned change before saving it as a new version. Nothing is saved.</p>
      <form onSubmit={submit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Rule">{(id) => (
            <Select id={id} value={key} onChange={(e) => { setKey(e.target.value); setResult(null); }}
              options={Object.entries(RULES).map(([k, r]) => ({ value: k, label: `${k} · ${r.title}` }))} />
          )}</Field>
          <Field label="Business date" hint="Empty: today">{(id) => <Input id={id} type="date" value={on} onChange={(e) => setOn(e.target.value)} />}</Field>
        </div>
        <fieldset className="grid gap-3 sm:grid-cols-3">
          <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Document facts</legend>
          {RULES[key].fields.map((f) => f.kind === 'bool' ? (
            <label key={f.name} className="flex items-center gap-2 self-end pb-2 text-sm text-slate-800">
              <input type="checkbox" checked={!!flags[f.name]} onChange={(e) => setFlags((x) => ({ ...x, [f.name]: e.target.checked }))} />
              {f.label}
            </label>
          ) : (
            <Field key={f.name} label={f.label} hint={f.hint}>{(id) => f.kind === 'select' ? (
              <Select id={id} value={values[f.name] ?? ''} onChange={(e) => setValues((x) => ({ ...x, [f.name]: e.target.value }))}
                options={(f.options ?? []).map((o) => ({ value: o, label: o ? label(o) : '–' }))} />
            ) : (
              <Input id={id} inputMode={f.kind === 'text' || f.kind === 'list' ? 'text' : 'decimal'} value={values[f.name] ?? ''}
                onChange={(e) => setValues((x) => ({ ...x, [f.name]: e.target.value }))} />
            )}</Field>
          ))}
        </fieldset>
        <details>
          <summary className="cursor-pointer text-sm font-medium text-[#1A56DB]">Scope and compare (optional)</summary>
          <div className="mt-2 grid gap-3 sm:grid-cols-4">
            {(['companyCode', 'plant', 'category', 'purchaseType'] as const).map((k) => (
              <Field key={k} label={label(k.replace(/([A-Z])/g, '_$1').toUpperCase())}>{(id) => (
                <Input id={id} value={scope[k]} onChange={(e) => setScope((x) => ({ ...x, [k]: e.target.value }))} />
              )}</Field>
            ))}
          </div>
          <div className="mt-3">
            <Field label="Draft body (JSON) to compare with the current version">{(id) => (
              <Textarea id={id} rows={6} value={draft} onChange={(e) => setDraft(e.target.value)} className="font-mono text-xs"
                placeholder='Copy the current body from "Rules & thresholds" and change a threshold' />
            )}</Field>
          </div>
        </details>
        {invalid && <p role="alert" className="text-sm text-red-700">{invalid}</p>}
        <ProblemBox error={run.error} />
        <Button type="submit" variant="primary" busy={run.isPending}>Simulate</Button>
      </form>

      {result && (
        <div className="mt-4 space-y-3" aria-live="polite">
          <p className="text-sm text-slate-700">Effective version <span className="font-mono font-semibold">{result.resolved.ref}</span> on {result.on}
            <span className="text-slate-500"> · {result.resolved.why}</span></p>
          <div className={`grid gap-3 ${result.compare ? 'md:grid-cols-2' : ''}`}>
            <Outcome title={`Current (${result.resolved.ref})`} d={result.result} />
            {result.compare && <Outcome title={`Draft${result.compare.changed ? ` · changes ${result.compare.changedFields.join(', ')}` : ' · no change'}`}
              d={result.compare.draft.result} />}
          </div>
          <details>
            <summary className="cursor-pointer text-xs font-medium text-[#1A56DB]">Versions considered ({result.candidates.length})</summary>
            <ul className="mt-1 space-y-1 text-xs text-slate-700">
              {result.candidates.map((c) => (
                <li key={c.version + c.effectiveFrom}>
                  <span className="font-mono">{c.version}</span> from {c.effectiveFrom}{c.effectiveTo ? ` to ${c.effectiveTo}` : ''} ·
                  {' '}{Object.keys(c.scope).length ? Object.entries(c.scope).map(([k, v]) => `${k}=${v}`).join(', ') : 'tenant default'} ·
                  {' '}{c.applies ? `applies (specificity ${c.specificity})` : `excluded: ${c.excludedBecause.join(', ')}`}
                </li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </Card>
  );
}
