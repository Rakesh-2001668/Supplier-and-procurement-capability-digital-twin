'use client';

import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, LinkButton, PageHeader, ProblemBox, Textarea } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { date, inr, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { MANAGE_ROLES, useCan } from '../_lib';

type Component = { code: string; type: string; label?: string; qty?: string; rate?: string; minutes?: string; amount?: string; of?: string[]; pct?: string; yieldLossPct?: string; index?: { code: string; baseDate?: string } };
type Spec = { unit?: string; inputs?: { code: string; label?: string; unit?: string; default?: string | number }[]; components: Component[]; marginPct: string | number };
type Model = { code: string; version: number; commodity: string; title: string; indexCode: string | null; spec: Spec; note: string | null };
type Evaluation = {
  model: string; unit: string; components: { component: string; label: string; amount: string; formula: string }[]; subtotal: string; marginPct: string; marginMinor: number;
  unitCost: string; unitCostMinor: number; indexLinks: { component: string; index: string; base: string; baseAsOf: string; current: string; currentAsOf: string; factor: string }[]; asOf: string;
};

function EvaluateDialog({ model, onClose }: { model: Model; onClose: () => void }) {
  const inputs = model.spec.inputs ?? [];
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(inputs.map((i) => [i.code, i.default != null ? String(i.default) : ''])));
  const [on, setOn] = useState('');
  const [result, setResult] = useState<Evaluation | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const missing = inputs.filter((i) => values[i.code] === '' || Number.isNaN(Number(values[i.code])));
  const run = useCommand(() => api.post<Evaluation>('/sourcing/should-cost/evaluate', { code: model.code, inputs: values, on: on || undefined }),
    { onSuccess: (r) => { setResult(r); setError(null); } });
  return (
    <Dialog open title={`Evaluate ${model.code} v${model.version}`} onClose={onClose} wide>
      <div className="space-y-4">
        <p className="text-sm text-slate-600">{model.title}. Amounts are rupees per {model.spec.unit ?? 'unit'}; material rates follow the index {model.indexCode ?? '(none)'} between the base date and the pricing date.</p>
        <div className="grid gap-3 md:grid-cols-4">
          {inputs.map((i) => (
            <Field key={i.code} label={`${i.label ?? i.code}${i.unit ? ` (${i.unit})` : ''}`}>{(id) => <Input id={id} type="number" min="0" step="any" value={values[i.code] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [i.code]: e.target.value }))} />}</Field>
          ))}
          <Field label="Pricing date" hint="Empty: today">{(id) => <Input id={id} type="date" value={on} onChange={(e) => setOn(e.target.value)} />}</Field>
        </div>
        <ProblemBox error={error} />
        {result && (
          <div className="space-y-3" aria-live="polite">
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="min-w-full text-sm">
                <caption className="sr-only">Should-cost components</caption>
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500"><tr><th scope="col" className="px-3 py-1">Component</th><th scope="col" className="px-3 py-1 text-right">Amount</th><th scope="col" className="px-3 py-1">Formula</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {result.components.map((c) => <tr key={c.component}><th scope="row" className="px-3 py-1 text-left font-medium">{label(c.label)}</th><td className="px-3 py-1 text-right tabular-nums">₹{c.amount}</td><td className="px-3 py-1 text-slate-600">{c.formula}</td></tr>)}
                  <tr><th scope="row" className="px-3 py-1 text-left font-normal text-slate-600">Subtotal</th><td className="px-3 py-1 text-right tabular-nums">₹{result.subtotal}</td><td /></tr>
                  <tr><th scope="row" className="px-3 py-1 text-left font-normal text-slate-600">Margin {result.marginPct}%</th><td className="px-3 py-1 text-right tabular-nums">{inr(result.marginMinor)}</td><td /></tr>
                  <tr className="font-semibold"><th scope="row" className="px-3 py-1 text-left">Should-cost per unit</th><td className="px-3 py-1 text-right tabular-nums">₹{result.unitCost}</td><td className="px-3 py-1 text-xs text-slate-500">{result.model} on {date(result.asOf)}</td></tr>
                </tbody>
              </table>
            </div>
            {result.indexLinks.length > 0 && (
              <ul className="text-sm text-slate-700">{result.indexLinks.map((l) => <li key={l.component}>{label(l.component)}: index {l.index} {l.base} ({date(l.baseAsOf)}) → {l.current} ({date(l.currentAsOf)}), factor <span className="font-semibold tabular-nums">{l.factor}</span></li>)}</ul>
            )}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Close</Button>
          <Button variant="primary" disabled={missing.length > 0} busy={run.isPending} onClick={() => run.mutate(undefined, { onError: (e) => setError(e) })}>Evaluate</Button>
        </div>
      </div>
    </Dialog>
  );
}

function ModelDialog({ from, onClose }: { from?: Model; onClose: () => void }) {
  const [code, setCode] = useState(from?.code ?? '');
  const [commodity, setCommodity] = useState(from?.commodity ?? '');
  const [title, setTitle] = useState(from?.title ?? '');
  const [indexCode, setIndexCode] = useState(from?.indexCode ?? '');
  const [note, setNote] = useState(from?.note ?? '');
  const [specText, setSpecText] = useState(JSON.stringify(from?.spec ?? {
    unit: 'EA', inputs: [{ code: 'net_weight_kg', label: 'Net weight', unit: 'kg' }, { code: 'rate_per_kg', label: 'Material rate', unit: '₹/kg' }, { code: 'margin', label: 'Margin', unit: '%' }],
    components: [{ code: 'MATERIAL', type: 'QTY_RATE', qty: 'net_weight_kg', rate: 'rate_per_kg', yieldLossPct: '5' }], marginPct: 'margin',
  }, null, 2));
  const [error, setError] = useState<ApiError | null>(null);
  let spec: unknown = null;
  let specError = '';
  try { spec = JSON.parse(specText); } catch (e) { specError = (e as Error).message; }
  const save = useCommand(() => api.post<{ code: string; version: number }>('/sourcing/should-cost/models', {
    code: code.trim().toUpperCase(), commodity: commodity.trim(), title: title.trim(), spec, index_code: indexCode.trim() || undefined, note: note.trim() || undefined,
  }), { success: (r) => `Model ${r.code} saved as version ${r.version}`, onSuccess: onClose });
  const ok = code.trim().length >= 2 && commodity.trim().length >= 2 && title.trim().length >= 3 && !specError;
  return (
    <Dialog open title={from ? `New version of ${from.code}` : 'New should-cost model'} onClose={onClose} wide>
      <div className="space-y-3">
        <p className="text-sm text-slate-600">A model is data, not code: cost components (quantity x rate, time x rate, fixed, percent of components), a margin and the index its material rates follow. Saving never edits a model: it creates the next version, and events that used version n keep reading it.</p>
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Code" required>{(id) => <Input id={id} value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} readOnly={!!from} maxLength={40} />}</Field>
          <Field label="Commodity" required>{(id) => <Input id={id} value={commodity} onChange={(e) => setCommodity(e.target.value)} maxLength={40} />}</Field>
          <Field label="Title" required>{(id) => <Input id={id} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />}</Field>
          <Field label="Index code" hint="e.g. LME_AL">{(id) => <Input id={id} value={indexCode} onChange={(e) => setIndexCode(e.target.value.toUpperCase())} maxLength={30} />}</Field>
        </div>
        <Field label="Specification (JSON)" error={specError ? `Not valid JSON: ${specError}` : undefined} required>{(id, d) => <Textarea id={id} aria-describedby={d} className="min-h-[220px] font-mono text-xs" value={specText} onChange={(e) => setSpecText(e.target.value)} />}</Field>
        <Field label="Note">{(id) => <Input id={id} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
        <ProblemBox error={error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!ok} busy={save.isPending} onClick={() => save.mutate(undefined, { onError: (e) => setError(e) })}>Save version</Button>
        </div>
      </div>
    </Dialog>
  );
}

export default function ShouldCostPage() {
  const can = useCan();
  const canManage = can(MANAGE_ROLES);
  const { data, isLoading, error } = useApi<Model[]>('/sourcing/should-cost/models');
  const [dialog, setDialog] = useState<{ kind: 'evaluate' | 'model'; model?: Model } | null>(null);
  const [view, setView] = useState<Model | null>(null);
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="SRC-03 · Should-cost" title="Should-cost models"
        subtitle="Data-driven cost models per commodity with their material rates linked to a published index. Attach one to an event as its baseline (SHOULD_COST) and as the benchmark every bid is compared with."
        actions={<>
          <LinkButton href="/pic/sourcing">Back to sourcing</LinkButton>
          {canManage && <Button variant="primary" onClick={() => setDialog({ kind: 'model' })}>New model</Button>}
        </>} />
      <Card>
        <DataTable<Model & Record<string, unknown>>
          caption="Should-cost models (latest version of each)" rows={(data ?? []).map((m) => ({ ...m, id: `${m.code}-${m.version}` }))} loading={isLoading} error={error} empty="No should-cost models"
          columns={[
            { key: 'code', header: 'Code', render: (m) => <span className="font-mono text-xs font-semibold">{m.code}</span> },
            { key: 'version', header: 'Version', align: 'right' },
            { key: 'commodity', header: 'Commodity' },
            { key: 'title', header: 'Title' },
            { key: 'indexCode', header: 'Index', render: (m) => m.indexCode ?? '–' },
            { key: 'components', header: 'Components', render: (m) => m.spec.components.map((c) => c.code).join(' + ') },
            { key: 'actions', header: '', render: (m) => (
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => setView(m)}>Specification</Button>
                {canManage && <Button variant="primary" onClick={() => setDialog({ kind: 'evaluate', model: m })}>Evaluate</Button>}
                {canManage && <Button onClick={() => setDialog({ kind: 'model', model: m })}>New version</Button>}
              </div>
            ) },
          ]} />
      </Card>
      {view && (
        <Dialog open title={`${view.code} v${view.version}: specification`} onClose={() => setView(null)} wide>
          <p className="mb-2 text-sm text-slate-600">{view.title}{view.note ? ` · ${view.note}` : ''}</p>
          <pre className="max-h-96 overflow-auto rounded-lg bg-slate-50 p-3 text-xs" tabIndex={0} aria-label="Specification JSON">{JSON.stringify(view.spec, null, 2)}</pre>
          <div className="mt-3 flex justify-end"><Button onClick={() => setView(null)}>Close</Button></div>
        </Dialog>
      )}
      {dialog?.kind === 'evaluate' && dialog.model && <EvaluateDialog model={dialog.model} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'model' && <ModelDialog from={dialog.model} onClose={() => setDialog(null)} />}
    </div>
  );
}
