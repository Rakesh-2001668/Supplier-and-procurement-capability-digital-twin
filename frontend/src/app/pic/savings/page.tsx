'use client';

import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Button, Card, DataTable, Dialog, Empty, Field, Input, Kpi, Loading, PageHeader, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { crore, date, inr, label, qty, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Initiative = {
  id?: string; ownerId?: string; number: string; title: string; stage: string; category: string | null; baselineMethod: string | null;
  baselinePriceMinor: number | null; newPriceMinor: number | null; annualVolume: string | null;
  negotiatedMinor: number; avoidanceMinor: number; realisedMinor: number;
  negotiatedCr: string; avoidanceCr: string; realisedCr: string; validated: boolean; canValidate?: boolean;
};
type Entry = { type: string; amountMinor: number; countsTowardBudget: boolean; formula: string; source: string | null; date: string };
type Leak = { po: string; kind: string; amountMinor: number };
type Waterfall = {
  initiative: string; stage: string; negotiatedMinor: number; contractedMinor: number; realisedMinor: number; avoidanceMinor: number;
  leakage: Leak[]; budgetImpactMinor: number; entries: Entry[];
};

// Bars carry their meaning in the axis label; colour only reinforces it.
const BAR_FILL: Record<string, string> = { negotiated: '#93b4f5', contracted: '#4f7fe6', realised: '#1A56DB', leakage: '#c2410c', avoidance: '#94a3b8' };

function WaterfallTooltip({ active, payload }: { active?: boolean; payload?: { payload: { name: string; minor: number; note: string } }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="max-w-xs rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
      <p className="font-semibold text-slate-900">{p.name}</p>
      <p className="tabular-nums text-slate-700">{inr(p.minor)} · {crore(p.minor)}</p>
      <p className="mt-0.5 text-slate-500">{p.note}</p>
    </div>
  );
}

function WaterfallView({ number, canValidate }: { number: string; canValidate: boolean }) {
  const { data, isLoading, error } = useApi<Waterfall>(`/savings/${encodeURIComponent(number)}/waterfall`);
  const validate = useCommand(() => api.post(`/savings/${encodeURIComponent(number)}/validate`), { success: `${number} validated by finance` });
  if (isLoading) return <Loading />;
  if (error || !data) return <ProblemBox error={error} />;

  const leakTotal = data.leakage.reduce((s, l) => s + Number(l.amountMinor), 0);
  const bars = [
    { key: 'negotiated', name: 'Negotiated', minor: data.negotiatedMinor, note: 'Agreed at award, on annual volume. Never counts toward budget.' },
    { key: 'contracted', name: 'Contracted', minor: data.contractedMinor, note: 'Carried into the executed contract price.' },
    { key: 'realised', name: 'Realised', minor: data.realisedMinor, note: 'From posted invoices only. Counts toward budget after finance validation.' },
    { key: 'leakage', name: 'Leakage', minor: leakTotal, note: 'Lost to off-contract buying or invoices above the agreed price.' },
    { key: 'avoidance', name: 'Avoidance', minor: data.avoidanceMinor, note: 'Cost increases avoided (e.g. index bands). Never counts toward budget.' },
  ].map((b) => ({ ...b, value: b.minor / 100 }));


  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold">{data.initiative}</span>
          <StatusChip status={data.stage} />
        </div>
        {data.stage === 'REALISING' && (canValidate ? (
          <div className="flex flex-col items-end gap-1">
            <Button variant="primary" busy={validate.isPending} onClick={() => validate.mutate()}>Validate realised savings</Button>
            <p className="text-xs text-slate-500">Finance validation; the initiative owner cannot validate (SOD-07).</p>
          </div>
        ) : (
          <p className="text-xs text-slate-500">Awaiting validation by a finance controller (the initiative owner cannot validate, SOD-07).</p>
        ))}
      </div>
      {validate.error && <ProblemBox error={validate.error} />}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Negotiated" value={crore(data.negotiatedMinor)} hint="not budget" />
        <Kpi label="Contracted" value={crore(data.contractedMinor)} hint="not budget" />
        <Kpi label="Realised" value={crore(data.realisedMinor)} hint="posted invoices" tone="good" />
        <Kpi label="Budget impact" value={inr(data.budgetImpactMinor)} hint={data.stage === 'VALIDATED' ? 'validated by finance' : 'zero until finance validates'}
          tone={data.budgetImpactMinor ? 'good' : 'default'} />
      </div>

      <Card title="Savings waterfall: negotiated → contracted → realised">
        <div style={{ height: 260 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bars} margin={{ top: 24, right: 12, bottom: 4, left: 8 }} barCategoryGap="28%">
              <CartesianGrid vertical={false} stroke="#e2e8f0" />
              <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#334155' }} axisLine={{ stroke: '#cbd5e1' }} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} width={72}
                tickFormatter={(v: number) => (v >= 1e7 ? `₹${(v / 1e7).toFixed(1)} Cr` : v >= 1e5 ? `₹${(v / 1e5).toFixed(1)} L` : `₹${v}`)} />
              <Tooltip cursor={{ fill: '#f1f5f9' }} content={<WaterfallTooltip />} />
              <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={56}>
                {bars.map((b) => <Cell key={b.key} fill={BAR_FILL[b.key]} />)}
                <LabelList dataKey="minor" position="top" formatter={(v: unknown) => crore(Number(v))} style={{ fontSize: 11, fill: '#334155' }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        {data.leakage.length > 0 ? (
          <div className="mt-4">
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Leakage</p>
            <DataTable<Leak> rows={data.leakage} columns={[
              { key: 'po', header: 'PO' },
              { key: 'kind', header: 'Kind', render: (r) => label(r.kind) },
              { key: 'amountMinor', header: 'Amount', align: 'right', render: (r) => inr(r.amountMinor) },
            ]} />
          </div>
        ) : <p className="mt-3 text-xs text-slate-500">No leakage: every invoiced line for this material was bought on contract at or below the agreed price.</p>}
      </Card>

      <Card title="Savings ledger">
        <DataTable<Entry> rows={data.entries} empty="No ledger entries yet" columns={[
          { key: 'type', header: 'Type', render: (r) => <StatusChip status={r.type} /> },
          { key: 'amountMinor', header: 'Amount', align: 'right', render: (r) => inr(r.amountMinor) },
          { key: 'countsTowardBudget', header: 'Budget', render: (r) => (r.countsTowardBudget ? 'Counts' : 'Does not count') },
          { key: 'formula', header: 'Formula', render: (r) => <span className="font-mono text-xs">{r.formula}</span> },
          { key: 'source', header: 'Source', render: (r) => r.source ?? '–' },
          { key: 'date', header: 'Date', render: (r) => date(r.date) },
        ]} />
      </Card>
    </div>
  );
}

export default function Savings() {
  const { data, isLoading, error } = useApi<Initiative[]>('/savings');
  const [selected, setSelected] = useState<string | null>(null);
  const current = selected ?? data?.[0]?.number ?? null;
  const me = useApi<Me>('/me');
  const canManage = !!me.data?.scopes.includes('savings:manage');
  const [dialog, setDialog] = useState<{ kind: 'new' } | { kind: 'negotiate' | 'lose'; initiative: Initiative } | null>(null);
  const isOwner = (r: Initiative) => !!me.data && (r.ownerId === me.data.userId || me.data.roles.includes('CPO'));

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="SAV-01/02 · Savings register" title="Savings"
        subtitle="Every saving is computed from a ledger with its formula and source document, so finance can audit each rupee."
        actions={canManage && <Button variant="primary" onClick={() => setDialog({ kind: 'new' })}>New initiative</Button>} />

      <Card title="Three kinds of savings (P12)">
        <dl className="grid gap-4 text-sm md:grid-cols-3">
          <div><dt className="font-semibold text-slate-900">Negotiated</dt>
            <dd className="mt-0.5 text-slate-600">Baseline price minus awarded price, times annual volume. A commitment, not cash: <strong>never counts toward budget</strong>.</dd></div>
          <div><dt className="font-semibold text-slate-900">Avoidance</dt>
            <dd className="mt-0.5 text-slate-600">Price increases the market would have imposed but the contract absorbed (e.g. index bands). <strong>Never counts toward budget</strong>.</dd></div>
          <div><dt className="font-semibold text-slate-900">Realised</dt>
            <dd className="mt-0.5 text-slate-600">Computed only from <strong>posted invoices</strong>. Counts toward budget only after a finance controller validates it.</dd></div>
        </dl>
      </Card>

      <Card title="Register">
        {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : !data?.length ? (
          <Empty title="No savings initiatives yet" hint={canManage ? 'Initiatives are created when a sourcing event is awarded, or here with New initiative.' : 'Initiatives are created when a sourcing event is awarded.'} />
        ) : (
          <DataTable<Initiative> rows={data} columns={[
            { key: 'number', header: 'Initiative', render: (r) => (
              <button type="button" onClick={() => setSelected(r.number)} aria-pressed={current === r.number}
                className={`font-mono font-medium hover:underline ${current === r.number ? 'text-[#0B1020] underline' : 'text-[#1A56DB]'}`}>{r.number}</button>
            ) },
            { key: 'title', header: 'Title', className: 'min-w-[200px]' },
            { key: 'stage', header: 'Stage', render: (r) => <StatusChip status={r.stage} /> },
            { key: 'baselineMethod', header: 'Baseline', render: (r) => <span>{label(r.baselineMethod)}<br /><span className="tabular-nums text-slate-500">{inr(r.baselinePriceMinor)}</span></span> },
            { key: 'newPriceMinor', header: 'New price', align: 'right', render: (r) => inr(r.newPriceMinor) },
            { key: 'annualVolume', header: 'Volume /yr', align: 'right', render: (r) => qty(r.annualVolume) },
            { key: 'negotiatedMinor', header: 'Negotiated', align: 'right', render: (r) => <span>{inr(r.negotiatedMinor)}<br /><span className="text-xs text-slate-500">₹{r.negotiatedCr} Cr</span></span> },
            { key: 'avoidanceMinor', header: 'Avoidance', align: 'right', render: (r) => <span>{inr(r.avoidanceMinor)}<br /><span className="text-xs text-slate-500">₹{r.avoidanceCr} Cr</span></span> },
            { key: 'realisedMinor', header: 'Realised', align: 'right', render: (r) => <span>{inr(r.realisedMinor)}<br /><span className="text-xs text-slate-500">₹{r.realisedCr} Cr</span></span> },
            { key: 'validated', header: 'Validated', render: (r) => (r.validated ? '✓ Yes' : 'No') },
            ...(canManage ? [{ key: 'actions', header: '', render: (r: Initiative) => (isOwner(r) && ['IDENTIFIED', 'NEGOTIATED'].includes(r.stage) ? (
              <div className="flex flex-col items-start gap-1">
                {r.stage === 'IDENTIFIED' && <Button onClick={() => setDialog({ kind: 'negotiate', initiative: r })}>Record negotiated price</Button>}
                <Button variant="danger" onClick={() => setDialog({ kind: 'lose', initiative: r })}>Mark lost</Button>
              </div>
            ) : null) }] : []),
          ]} />
        )}
      </Card>

      {current && <WaterfallView key={current} number={current} canValidate={!!data?.find((r) => r.number === current)?.canValidate} />}

      {dialog?.kind === 'new' && <NewInitiativeDialog onClose={() => setDialog(null)} onCreated={(n) => { setSelected(n); setDialog(null); }} />}
      {dialog?.kind === 'negotiate' && <NegotiateDialog initiative={dialog.initiative} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'lose' && <LoseDialog initiative={dialog.initiative} onClose={() => setDialog(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------- SAV-01 manual initiatives
type Me = { userId: string; roles: string[]; scopes: string[] };
type Reference = { materials: { number: string; description: string; uom: string; category: string | null; standardPriceMinor: number | null }[]; suppliers: { code: string; name: string; status: string }[] };

const BASELINES = [
  { value: 'LAST_PRICE', label: 'Last price paid (latest PO, else info record)' },
  { value: 'WAVG_12M', label: 'Weighted average of invoices, last 12 months' },
  { value: 'STANDARD', label: 'Standard price from the material master' },
  { value: 'SHOULD_COST', label: 'Should-cost model (enter the price)' },
];

function DialogActions({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  return <div className="mt-4 flex justify-end gap-2"><Button onClick={onClose}>Cancel</Button>{children}</div>;
}

function NewInitiativeDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (number: string) => void }) {
  const ref = useApi<Reference>('/reference');
  const materials = ref.data?.materials ?? [];
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState('');
  const [method, setMethod] = useState('LAST_PRICE');
  const [material, setMaterial] = useState('');
  const [volume, setVolume] = useState('');
  const [price, setPrice] = useState('');
  const shouldCost = method === 'SHOULD_COST';
  const categories = [...new Set(materials.map((m) => m.category).filter((c): c is string => !!c))].sort();
  const chosen = materials.find((m) => m.number === material);
  const needsPrice = shouldCost || !material;
  const valid = !!title.trim() && !!category.trim() && Number(volume) > 0 && (!needsPrice || Number(price) > 0);
  const create = useCommand(() => api.post<{ number: string; baseline_price_minor: number }>('/savings/initiatives', {
    title: title.trim(), category: category.trim().toUpperCase(), baseline_method: method, annual_volume: volume,
    material: material || undefined, baseline_price_minor: price ? rupeesToMinor(price) : undefined,
  }), { success: (r) => `${r.number} identified with baseline ${inr(r.baseline_price_minor)}`, onSuccess: (r) => onCreated(r.number) });

  return (
    <Dialog open title="New savings initiative" onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="md:col-span-2">
          <Field label="Title (required)">{(id) => <Input id={id} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Renegotiate DC-331 housing price with index link" />}</Field>
        </div>
        <Field label="Material (optional)" hint="Needed for last-price, 12-month average and standard baselines">{(id) => (
          <Select id={id} value={material} onChange={(e) => {
            setMaterial(e.target.value);
            const m = materials.find((x) => x.number === e.target.value);
            if (m?.category && !category) setCategory(m.category);
          }} options={[{ value: '', label: ref.isLoading ? 'Loading materials…' : 'No material (enter a baseline price)' }, ...materials.map((m) => ({ value: m.number, label: `${m.number} · ${m.description}` }))]} />
        )}</Field>
        <Field label="Category (required)">{(id) => (
          <>
            <Input id={id} list="initiative-categories" value={category} onChange={(e) => setCategory(e.target.value.toUpperCase())} placeholder="e.g. ALU-DIECAST" />
            <datalist id="initiative-categories">{categories.map((c) => <option key={c} value={c} />)}</datalist>
          </>
        )}</Field>
        <Field label="Baseline method" hint="Fixed at creation; the derivation is written to the audit trail">{(id) => <Select id={id} value={method} onChange={(e) => setMethod(e.target.value)} options={BASELINES} />}</Field>
        <Field label={`Annual volume (required)${chosen ? ` in ${chosen.uom}` : ''}`}>{(id) => <Input id={id} type="number" min="0" step="any" value={volume} onChange={(e) => setVolume(e.target.value)} placeholder="e.g. 120000" />}</Field>
        {(needsPrice || price) && (
          <Field label={`Baseline price per unit in ₹${needsPrice ? ' (required)' : ''}`} hint={shouldCost ? 'The should-cost price from your cost model' : 'Used because no material is selected'}>{(id) => (
            <Input id={id} type="number" min="0" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="e.g. 395.50" />
          )}</Field>
        )}
      </div>
      {method === 'STANDARD' && chosen && <p className="mt-2 text-xs text-slate-500">Standard price of {chosen.number}: {chosen.standardPriceMinor ? inr(chosen.standardPriceMinor) : 'not set – choose another method'}</p>}
      <p className="mt-3 text-xs text-slate-500">The initiative starts as Identified. Negotiated savings never count toward budget; realised savings come from posted invoices only.</p>
      {create.error && <div className="mt-3"><ProblemBox error={create.error} /></div>}
      <DialogActions onClose={onClose}>
        <Button variant="primary" disabled={!valid} busy={create.isPending} onClick={() => create.mutate()}>Create initiative</Button>
      </DialogActions>
    </Dialog>
  );
}

function NegotiateDialog({ initiative, onClose }: { initiative: Initiative; onClose: () => void }) {
  const ref = useApi<Reference>('/reference');
  const suppliers = ref.data?.suppliers ?? [];
  const [price, setPrice] = useState('');
  const [supplier, setSupplier] = useState('');
  const [evidence, setEvidence] = useState('');
  const effective = supplier || suppliers[0]?.code || '';
  const newMinor = price ? rupeesToMinor(price) : 0;
  const preview = initiative.baselinePriceMinor !== null && newMinor > 0 && initiative.annualVolume
    ? Math.round((initiative.baselinePriceMinor - newMinor) * Number(initiative.annualVolume)) : null;
  const valid = newMinor > 0 && !!effective && !!evidence.trim();
  const save = useCommand(() => api.post(`/savings/${encodeURIComponent(initiative.number)}/negotiate`, { new_price_minor: newMinor, supplier: effective, evidence: evidence.trim() }), {
    success: `${initiative.number} negotiated at ${inr(newMinor)} per unit`, onSuccess: onClose });
  return (
    <Dialog open title={`Record negotiated price – ${initiative.number}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">{initiative.title} · baseline {label(initiative.baselineMethod)} {inr(initiative.baselinePriceMinor)} · {qty(initiative.annualVolume)} per year.</p>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Negotiated price per unit in ₹ (required)">{(id) => <Input id={id} type="number" min="0" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} />}</Field>
        <Field label="Supplier">{(id) => (
          <Select id={id} value={effective} onChange={(e) => setSupplier(e.target.value)}
            options={suppliers.length ? suppliers.map((s) => ({ value: s.code, label: `${s.code} · ${s.name}` })) : [{ value: '', label: ref.isLoading ? 'Loading suppliers…' : 'No suppliers' }]} />
        )}</Field>
        <div className="md:col-span-2">
          <Field label="Evidence (required)" hint="Quote, e-mail or minutes that record the agreed price">{(id) => (
            <Textarea id={id} value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="e.g. Supplier letter KD/2026/114 dated 21 Oct 2026" />
          )}</Field>
        </div>
      </div>
      {preview !== null && (
        <p className={`mt-3 text-sm ${preview < 0 ? 'text-red-700' : 'text-slate-700'}`}>
          Negotiated saving: <span className="font-semibold tabular-nums">{inr(preview)}</span> per year ({crore(preview)}). It does not count toward budget.
        </p>
      )}
      {save.error && <div className="mt-3"><ProblemBox error={save.error} /></div>}
      <DialogActions onClose={onClose}>
        <Button variant="primary" disabled={!valid} busy={save.isPending} onClick={() => save.mutate()}>Record negotiated price</Button>
      </DialogActions>
    </Dialog>
  );
}

function LoseDialog({ initiative, onClose }: { initiative: Initiative; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const lose = useCommand(() => api.post(`/savings/${encodeURIComponent(initiative.number)}/lose`, { reason: reason.trim() }), {
    success: `${initiative.number} marked lost`, onSuccess: onClose });
  return (
    <Dialog open title={`Mark lost – ${initiative.number}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">{initiative.title}. A lost initiative stays in the register with its ledger; it can no longer be negotiated or contracted.</p>
      <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Supplier refused the price; volume moved to an existing contract" />}</Field>
      {lose.error && <div className="mt-3"><ProblemBox error={lose.error} /></div>}
      <DialogActions onClose={onClose}>
        <Button variant="danger" disabled={!reason.trim()} busy={lose.isPending} onClick={() => lose.mutate()}>Mark lost</Button>
      </DialogActions>
    </Dialog>
  );
}
