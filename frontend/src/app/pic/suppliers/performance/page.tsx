'use client';

import Link from 'next/link';
import { useState } from 'react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Button, Card, DataTable, Dialog, Empty, Field, Input, Kpi, LinkButton, Loading, PageHeader, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, label, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { useMe } from '../../mrp/_components';

type TrendPoint = { period: string; otifPct: string | null; ppm: string | null; invoiceAccuracyPct: string | null; receipts: number; invoices: number };
type Performance = { supplier: string; name: string; trend: TrendPoint[]; latest: TrendPoint; openCapas: number; categories: string[] };
type Capa = {
  id: string; number: string; supplier: string | null; source_type: string; source_ref: string; finding: string; root_cause: string | null;
  actions: { action?: string; due?: string; [k: string]: unknown }[] | null; due_date: string; status: string; closed_at: string | null; created_at: string;
};
type Reference = { suppliers: { code: string; name: string; status: string }[] };

const OTIF = '#2a78d6';
const INVOICE = '#eb6834';
const PPM = '#6250d6';

const pct = (v: string | null | undefined) => (v === null || v === undefined ? '–' : `${Number(v).toFixed(1)}%`);
const num = (v: string | null) => (v === null ? null : Number(v));
const monthLabel = (p: string) => new Date(Number(p.slice(0, 4)), Number(p.slice(5, 7)) - 1, 1).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });

function TrendTooltip({ active, payload }: { active?: boolean; payload?: { payload: { name: string; p: TrendPoint } }[] }) {
  if (!active || !payload?.length) return null;
  const { name, p } = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
      <p className="font-semibold text-slate-900">{name}</p>
      <p className="tabular-nums text-slate-700">OTIF {pct(p.otifPct)} · {p.receipts} receipt(s)</p>
      <p className="tabular-nums text-slate-700">Invoice accuracy {pct(p.invoiceAccuracyPct)} · {p.invoices} invoice(s)</p>
      <p className="tabular-nums text-slate-700">PPM {p.ppm === null ? '–' : qty(p.ppm)}</p>
    </div>
  );
}

export default function SupplierPerformance() {
  const { scopes, roles } = useMe();
  const perf = useApi<Performance[]>('/supplier-performance');
  const capas = useApi<Capa[]>('/capas');
  const [selected, setSelected] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ kind: 'status'; supplier: string; category: string; status: 'PREFERRED' | 'EXITED' } | { kind: 'verify'; capa: Capa } | { kind: 'open'; supplier?: string } | null>(null);
  const canStatus = !roles.length || roles.some((r) => ['SUPPLIER_MANAGER', 'CATEGORY_MANAGER'].includes(r));
  const canVerify = scopes.includes('quality:decide');
  const canOpenCapa = scopes.includes('quality:decide') || scopes.includes('supplier:manage');
  const list = perf.data ?? [];
  const current = list.find((s) => s.supplier === selected) ?? list[0];
  const capaRows = capas.data ?? [];
  const openCapas = capaRows.filter((c) => c.status !== 'CLOSED');
  const withOtif = list.filter((s) => s.latest?.otifPct !== null && s.latest?.otifPct !== undefined);
  const avgOtif = withOtif.length ? withOtif.reduce((s, x) => s + Number(x.latest.otifPct), 0) / withOtif.length : null;

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="SLM-03 · Supplier performance" title="Performance scorecard"
        subtitle="Monthly OTIF, PPM and first-pass invoice accuracy from goods receipts, inspection lots and invoices. Preferred status needs evidence over the last three scorecards; CAPAs are closed only after quality verifies effectiveness."
        actions={<>
          <LinkButton href="/pic/suppliers">Suppliers</LinkButton>
          <LinkButton href="/pic/suppliers/risk">Risk monitor</LinkButton>
          {canOpenCapa && <Button variant="primary" onClick={() => setDialog({ kind: 'open', supplier: current?.supplier })}>Open CAPA</Button>}
        </>} />

      {perf.isLoading ? <Loading /> : perf.error ? <ProblemBox error={perf.error} /> : !list.length ? (
        <Empty title="No scorecards yet" hint="Scorecards are computed from receipts, inspections and invoices each period." />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Suppliers scored" value={list.length} />
            <Kpi label="Average OTIF (latest)" value={avgOtif === null ? '–' : `${avgOtif.toFixed(1)}%`} hint={`${withOtif.length} supplier(s) with receipts`} tone={avgOtif !== null && avgOtif < 90 ? 'warn' : 'good'} />
            <Kpi label="Open CAPAs" value={openCapas.length} tone={openCapas.length ? 'warn' : 'good'} />
            <Kpi label="Awaiting verification" value={capaRows.filter((c) => c.status === 'RESPONDED').length} hint="supplier responded" />
          </div>

          <Card title="Latest scorecard by supplier">
            <DataTable<Performance & { id: string }> rows={list.map((s) => ({ ...s, id: s.supplier }))} columns={[
              { key: 'supplier', header: 'Supplier', render: (s) => (
                <button type="button" onClick={() => setSelected(s.supplier)} aria-pressed={current?.supplier === s.supplier}
                  className={`text-left font-medium hover:underline ${current?.supplier === s.supplier ? 'text-[#0B1020] underline' : 'text-[#1A56DB]'}`}>
                  {s.name} <span className="font-mono text-xs text-slate-500">{s.supplier}</span>
                </button>
              ) },
              { key: 'period', header: 'Period', render: (s) => monthLabel(s.latest.period) },
              { key: 'otif', header: 'OTIF', align: 'right', render: (s) => pct(s.latest.otifPct) },
              { key: 'ppm', header: 'PPM', align: 'right', render: (s) => (s.latest.ppm === null ? '–' : qty(s.latest.ppm)) },
              { key: 'inv', header: 'Invoice accuracy', align: 'right', render: (s) => pct(s.latest.invoiceAccuracyPct) },
              { key: 'openCapas', header: 'Open CAPAs', align: 'right' },
              { key: 'categories', header: 'Category status', render: (s) => (
                <ul className="space-y-1">
                  {s.categories.map((entry) => {
                    const [cat, st] = entry.split(':');
                    return (
                      <li key={entry} className="flex flex-wrap items-center gap-1.5">
                        <span className="font-mono text-[11px] text-slate-600">{cat}</span><StatusChip status={st} />
                        {canStatus && st === 'QUALIFIED' && (
                          <button type="button" className="text-xs font-medium text-[#1A56DB] hover:underline" onClick={() => setDialog({ kind: 'status', supplier: s.supplier, category: cat, status: 'PREFERRED' })}>Make preferred</button>
                        )}
                        {canStatus && !['EXITED', 'BLOCKED'].includes(st) && (
                          <button type="button" className="text-xs font-medium text-red-700 hover:underline" onClick={() => setDialog({ kind: 'status', supplier: s.supplier, category: cat, status: 'EXITED' })}>Exit</button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              ) },
            ]} />
          </Card>

          {current && <TrendCharts s={current} />}
        </>
      )}

      <Card title="Corrective and preventive actions (CAPA)">
        <DataTable<Capa> rows={capaRows} loading={capas.isLoading} error={capas.error} empty="No CAPAs" columns={[
          { key: 'number', header: 'CAPA', render: (c) => <span className="font-mono text-xs font-semibold">{c.number}</span> },
          { key: 'supplier', header: 'Supplier', render: (c) => (c.supplier ? <Link href={`/pic/suppliers/${encodeURIComponent(c.supplier)}`} className="font-mono text-xs font-medium text-[#1A56DB] hover:underline">{c.supplier}</Link> : '–') },
          { key: 'source_ref', header: 'Source', render: (c) => <span className="text-xs">{label(c.source_type)}<br /><span className="font-mono">{c.source_ref}</span></span> },
          { key: 'finding', header: 'Finding', className: 'min-w-[200px]' },
          { key: 'root_cause', header: 'Root cause and actions', className: 'min-w-[240px]', render: (c) => (
            c.root_cause || c.actions?.length ? (
              <div className="text-xs text-slate-700">
                {c.root_cause && <p>{c.root_cause}</p>}
                {!!c.actions?.length && <ul className="mt-1 list-disc space-y-0.5 pl-4">{c.actions.map((a, i) => <li key={i}>{String(a.action ?? JSON.stringify(a))}{a.due ? ` · due ${date(String(a.due))}` : ''}</li>)}</ul>}
              </div>
            ) : <span className="text-xs text-slate-400">awaiting supplier response</span>
          ) },
          { key: 'due_date', header: 'Due', render: (c) => {
            const overdue = c.status !== 'CLOSED' && new Date(c.due_date) < new Date();
            return <span className={overdue ? 'font-semibold text-red-700' : ''}>{date(c.due_date)}{overdue ? ' (overdue)' : ''}</span>;
          } },
          { key: 'status', header: 'Status', render: (c) => <StatusChip status={c.status} /> },
          { key: 'actions', header: '', render: (c) => (canVerify && c.status === 'RESPONDED' ? <Button variant="primary" onClick={() => setDialog({ kind: 'verify', capa: c })}>Verify</Button> : null) },
        ]} />
        {!canVerify && capaRows.some((c) => c.status === 'RESPONDED') && <p className="mt-2 text-xs text-slate-500">Responded CAPAs are verified by a quality inspector.</p>}
      </Card>

      {dialog?.kind === 'status' && <CategoryStatusDialog {...dialog} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'verify' && <VerifyDialog capa={dialog.capa} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'open' && <OpenCapaDialog initial={dialog.supplier} onClose={() => setDialog(null)} />}
    </div>
  );
}

function TrendCharts({ s }: { s: Performance }) {
  const rows = s.trend.map((p) => ({ name: monthLabel(p.period), otif: num(p.otifPct), invoice: num(p.invoiceAccuracyPct), ppm: num(p.ppm), p }));
  const hasPpm = rows.some((r) => r.ppm !== null);
  return (
    <Card title={<span>{s.name} <span className="font-mono text-xs font-normal text-slate-500">{s.supplier}</span> · trend</span>}
      actions={<Link href={`/pic/suppliers/${encodeURIComponent(s.supplier)}`} className="text-xs font-medium text-[#1A56DB] hover:underline">Supplier 360 →</Link>}>
      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">OTIF and invoice accuracy (%)</p>
          <div style={{ height: 240 }} role="img" aria-label={`Line chart of OTIF and invoice accuracy per month for ${s.supplier}`}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
                <CartesianGrid vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={{ stroke: '#cbd5e1' }} tickLine={false} minTickGap={12} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} width={40} tickFormatter={(v: number) => `${v}%`} />
                <Tooltip content={<TrendTooltip />} cursor={{ stroke: '#94a3b8', strokeWidth: 1 }} />
                <Legend verticalAlign="top" height={28} wrapperStyle={{ fontSize: 12, color: '#334155' }} />
                <Line dataKey="otif" name="OTIF" stroke={OTIF} strokeWidth={2} dot={{ r: 3, fill: OTIF, stroke: '#ffffff', strokeWidth: 1 }} connectNulls={false} isAnimationActive={false} />
                <Line dataKey="invoice" name="Invoice accuracy" stroke={INVOICE} strokeWidth={2} dot={{ r: 3, fill: INVOICE, stroke: '#ffffff', strokeWidth: 1 }} connectNulls={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Defects (PPM)</p>
          {!hasPpm ? <Empty title="No inspected receipts" hint="PPM appears once goods receipts are inspected." /> : (
            <div style={{ height: 240 }} role="img" aria-label={`Line chart of PPM per month for ${s.supplier}`}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
                  <CartesianGrid vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={{ stroke: '#cbd5e1' }} tickLine={false} minTickGap={12} />
                  <YAxis tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} width={48} />
                  <Tooltip content={<TrendTooltip />} cursor={{ stroke: '#94a3b8', strokeWidth: 1 }} />
                  <Line dataKey="ppm" name="PPM" stroke={PPM} strokeWidth={2} dot={{ r: 3, fill: PPM, stroke: '#ffffff', strokeWidth: 1 }} connectNulls={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
      <div className="mt-4">
        <DataTable<TrendPoint & { id: string }> rows={[...s.trend].reverse().map((p) => ({ ...p, id: p.period }))} columns={[
          { key: 'period', header: 'Period', render: (p) => monthLabel(p.period) },
          { key: 'otifPct', header: 'OTIF', align: 'right', render: (p) => pct(p.otifPct) },
          { key: 'receipts', header: 'Receipts', align: 'right' },
          { key: 'ppm', header: 'PPM', align: 'right', render: (p) => (p.ppm === null ? '–' : qty(p.ppm)) },
          { key: 'invoiceAccuracyPct', header: 'Invoice accuracy', align: 'right', render: (p) => pct(p.invoiceAccuracyPct) },
          { key: 'invoices', header: 'Invoices', align: 'right' },
        ]} />
      </div>
    </Card>
  );
}

function Actions({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  return <div className="mt-4 flex justify-end gap-2"><Button onClick={onClose}>Cancel</Button>{children}</div>;
}

function CategoryStatusDialog({ supplier, category, status, onClose }: { supplier: string; category: string; status: 'PREFERRED' | 'EXITED'; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const save = useCommand(() => api.post(`/suppliers/${encodeURIComponent(supplier)}/categories/${encodeURIComponent(category)}/status`, { status, reason: reason.trim() }), {
    success: `${supplier} is now ${label(status).toLowerCase()} for ${category}`, onSuccess: onClose });
  const preferred = status === 'PREFERRED';
  return (
    <Dialog open title={`${preferred ? 'Make preferred' : 'Exit category'} – ${supplier} · ${category}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">{preferred
        ? 'Preferred needs Qualified status plus average OTIF and worst PPM within the tenant limits over the last three scorecards. The rule is checked when you confirm.'
        : 'Exiting ends the relationship for this category: the supplier can no longer be invited or awarded in it. Open purchase orders are kept and flagged in the audit trail.'}</p>
      <Field label="Reason (required)">{(id) => (
        <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder={preferred ? 'e.g. OTIF above 97% for three periods; zero escapes' : 'e.g. Repeated porosity escapes; volume moved to the alternate source'} />
      )}</Field>
      {save.error && <div className="mt-3"><ProblemBox error={save.error} /></div>}
      <Actions onClose={onClose}>
        <Button variant={preferred ? 'primary' : 'danger'} disabled={!reason.trim()} busy={save.isPending} onClick={() => save.mutate()}>{preferred ? 'Make preferred' : 'Exit category'}</Button>
      </Actions>
    </Dialog>
  );
}

function VerifyDialog({ capa, onClose }: { capa: Capa; onClose: () => void }) {
  const [effective, setEffective] = useState(true);
  const [comment, setComment] = useState('');
  const verify = useCommand(() => api.post<Capa>(`/capas/${encodeURIComponent(capa.number)}/verify`, { effective, comment: comment.trim() }), {
    success: (c) => `${capa.number} ${c.status === 'CLOSED' ? 'verified effective and closed' : 'reopened – the supplier must respond again'}`, onSuccess: onClose });
  return (
    <Dialog open title={`Verify CAPA – ${capa.number}`} onClose={onClose}>
      <p className="mb-1 text-sm text-slate-700">{capa.finding}</p>
      {capa.root_cause && <p className="mb-3 text-sm text-slate-600">Root cause: {capa.root_cause}</p>}
      <fieldset>
        <legend className="text-xs font-medium text-slate-700">Effectiveness</legend>
        <div className="mt-1 flex flex-wrap gap-4 text-sm">
          <label className="inline-flex items-center gap-2"><input type="radio" name="effective" className="accent-[#1A56DB]" checked={effective} onChange={() => setEffective(true)} /> Effective – close the CAPA</label>
          <label className="inline-flex items-center gap-2"><input type="radio" name="effective" className="accent-[#1A56DB]" checked={!effective} onChange={() => setEffective(false)} /> Not effective – reopen</label>
        </div>
      </fieldset>
      <div className="mt-3">
        <Field label="Verification comment (required)">{(id) => (
          <Textarea id={id} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="e.g. Three lots since the fix inspected at 0 PPM; thermocouple alarms verified on cell 4" />
        )}</Field>
      </div>
      {verify.error && <div className="mt-3"><ProblemBox error={verify.error} /></div>}
      <Actions onClose={onClose}>
        <Button variant="primary" disabled={!comment.trim()} busy={verify.isPending} onClick={() => verify.mutate()}>Record verification</Button>
      </Actions>
    </Dialog>
  );
}

function OpenCapaDialog({ initial, onClose }: { initial?: string; onClose: () => void }) {
  const ref = useApi<Reference>('/reference');
  const suppliers = ref.data?.suppliers ?? [];
  const [supplier, setSupplier] = useState(initial ?? '');
  const [sourceRef, setSourceRef] = useState('');
  const [finding, setFinding] = useState('');
  const [dueDays, setDueDays] = useState('30');
  const effective = supplier || suppliers[0]?.code || '';
  const valid = !!effective && !!sourceRef.trim() && !!finding.trim() && Number(dueDays) >= 1;
  const open = useCommand(() => api.post<Capa>('/capas', { supplier: effective, source_ref: sourceRef.trim(), finding: finding.trim(), due_days: Number(dueDays) }), {
    success: (c) => `${c.number} opened for ${effective}, due ${date(c.due_date)}`, onSuccess: onClose });
  return (
    <Dialog open title="Open CAPA" onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Supplier">{(id) => (
          <Select id={id} value={effective} onChange={(e) => setSupplier(e.target.value)}
            options={suppliers.length ? suppliers.map((s) => ({ value: s.code, label: `${s.code} · ${s.name}` })) : [{ value: '', label: ref.isLoading ? 'Loading suppliers…' : 'No suppliers' }]} />
        )}</Field>
        <Field label="Source reference (required)" hint="Inspection lot, complaint or audit reference. One CAPA per supplier and source.">{(id) => (
          <Input id={id} value={sourceRef} onChange={(e) => setSourceRef(e.target.value)} placeholder="e.g. QL-2231 or AUD-2026-07" />
        )}</Field>
        <div className="md:col-span-2">
          <Field label="Finding (required)">{(id) => <Textarea id={id} value={finding} onChange={(e) => setFinding(e.target.value)} placeholder="e.g. 14 housings rejected for blow-holes on GR-90310" />}</Field>
        </div>
        <Field label="Response due in (days)">{(id) => <Input id={id} type="number" min="1" max="180" value={dueDays} onChange={(e) => setDueDays(e.target.value)} />}</Field>
      </div>
      {open.error && <div className="mt-3"><ProblemBox error={open.error} /></div>}
      <Actions onClose={onClose}>
        <Button variant="primary" disabled={!valid} busy={open.isPending} onClick={() => open.mutate()}>Open CAPA</Button>
      </Actions>
    </Dialog>
  );
}
