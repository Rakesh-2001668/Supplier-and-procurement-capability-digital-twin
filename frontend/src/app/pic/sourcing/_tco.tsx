'use client';

// TCO stack, its component trace and the what-if simulator (POST /v1/sourcing/tco/simulate).
import { useState } from 'react';
import { Button, Field, Input, ProblemBox, Select } from '@/components/pic/ui';
import type { ApiError } from '@/lib/pic/api';
import { api } from '@/lib/pic/api';
import { inr, label } from '@/lib/pic/format';
import { useCommand } from '@/lib/pic/hooks';
import { TCO_LABELS, TraceItem } from './_lib';

export type Simulation = {
  supplier: string; rule: string; priceInr: { minor: number; quotedMinor: number | null; currency: string; steps?: unknown };
  tcoMinor: number; parts: Record<string, number>; rounding: number; incomplete: boolean; missing: string[]; trace: TraceItem[];
};

const STATUS_TONE: Record<string, string> = {
  MISSING: 'bg-red-50 text-red-800 ring-red-200', ESTIMATED: 'bg-amber-50 text-amber-800 ring-amber-200', NOT_QUOTED: 'bg-slate-100 text-slate-700 ring-slate-200',
  BID: 'bg-emerald-50 text-emerald-800 ring-emerald-200', INCLUDED: 'bg-slate-100 text-slate-700 ring-slate-200', NOT_APPLICABLE: 'bg-slate-100 text-slate-700 ring-slate-200',
};

export function TraceStatus({ status }: { status?: string }) {
  return <span className={`inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ring-inset ${STATUS_TONE[status ?? ''] ?? 'bg-blue-50 text-blue-800 ring-blue-200'}`}>{status ? status.replace(/_/g, ' ') : '–'}</span>;
}

/** The TCO components of one bid line that add up to the total (rounding shown separately so the stack always adds up). */
export function TcoStack({ parts, totalMinor, missing }: { parts: Record<string, number> | null | undefined; totalMinor: number; missing?: string[] }) {
  if (!parts) return <p className="text-xs text-slate-500">No component breakdown for this bid.</p>;
  const sum = Object.values(parts).reduce((a, b) => a + b, 0);
  const rounding = totalMinor - sum;
  return (
    <table className="w-full text-xs">
      <caption className="sr-only">Total cost of ownership stack in rupees per base unit</caption>
      <tbody className="divide-y divide-slate-100">
        {TCO_LABELS.filter(([k]) => parts[k] !== undefined).map(([k, name]) => (
          <tr key={k}>
            <th scope="row" className="py-0.5 pr-3 text-left font-normal text-slate-600">{name}{missing?.includes(k) && <span className="ml-1 font-semibold text-red-700">· MISSING (not zero)</span>}</th>
            <td className={`py-0.5 text-right tabular-nums ${parts[k] < 0 ? 'text-emerald-700' : ''}`}>{inr(parts[k])}</td>
          </tr>
        ))}
        <tr><th scope="row" className="py-0.5 pr-3 text-left font-normal text-slate-500">Rounding</th><td className="py-0.5 text-right tabular-nums text-slate-500">{inr(rounding)}</td></tr>
        <tr className="font-semibold"><th scope="row" className="py-1 pr-3 text-left">Total cost of ownership</th><td className="py-1 text-right tabular-nums">{inr(totalMinor)}</td></tr>
      </tbody>
    </table>
  );
}

export function TraceTable({ trace }: { trace: TraceItem[] }) {
  const rows = trace.filter((t) => t.status || t.formula);
  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-full text-xs">
        <caption className="sr-only">Component trace: value, status, formula and inputs of every TCO component</caption>
        <thead className="bg-slate-50 text-left uppercase tracking-wide text-slate-500">
          <tr><th scope="col" className="px-2 py-1">Component</th><th scope="col" className="px-2 py-1 text-right">Value</th><th scope="col" className="px-2 py-1">Status</th><th scope="col" className="px-2 py-1">Formula</th><th scope="col" className="px-2 py-1">Inputs</th></tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white align-top">
          {rows.map((t) => (
            <tr key={t.component}>
              <th scope="row" className="px-2 py-1 text-left font-medium">{t.component === 'paymentTermValue' ? 'Payment-term value' : label(t.component)}</th>
              <td className="px-2 py-1 text-right tabular-nums">{t.valueMinor !== undefined ? inr(Number(t.valueMinor)) : '–'}</td>
              <td className="px-2 py-1"><TraceStatus status={t.status} /></td>
              <td className="px-2 py-1 text-slate-700">{t.formula ?? '–'}</td>
              <td className="px-2 py-1 font-mono text-[10px] text-slate-500">{t.inputs && Object.keys(t.inputs).length ? JSON.stringify(t.inputs) : '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Draft = Record<string, string>;
const blank = (v: string | undefined) => (v ?? '').trim() === '';

export function TcoSimulator({ suppliers, defaultCategory = '', defaultSupplier = '' }: { suppliers?: string[]; defaultCategory?: string; defaultSupplier?: string }) {
  const [d, setD] = useState<Draft>({
    supplier: defaultSupplier, category: defaultCategory, material: '', unit_price: '', freight: '', duty: '', packaging: '', payment_terms_days: '60',
    lead_time_days: '21', currency: 'INR', incoterm: '', origin: '', hs_code: '', moq: '', uom_factor: '', tax_rate_pct: '', tax_included: 'false', annual_qty: '', on: '',
  });
  const [result, setResult] = useState<Simulation | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const set = (patch: Draft) => setD((cur) => ({ ...cur, ...patch }));
  const problems: string[] = [];
  if (blank(d.supplier)) problems.push('Supplier code');
  if (blank(d.category)) problems.push('Category');
  if (!(Number(d.unit_price) > 0)) problems.push('Unit price greater than zero');
  if (blank(d.payment_terms_days) || !(Number(d.payment_terms_days) >= 0)) problems.push('Payment terms (days)');
  if (blank(d.lead_time_days) || !(Number(d.lead_time_days) >= 0)) problems.push('Lead time (days)');
  const run = useCommand(() => {
    const line: Record<string, unknown> = {
      line: 1, unit_price: d.unit_price, payment_terms_days: Number(d.payment_terms_days), lead_time_days: Number(d.lead_time_days),
      tax_included: d.tax_included === 'true',
    };
    for (const k of ['freight', 'duty', 'packaging', 'moq', 'uom_factor', 'tax_rate_pct']) if (!blank(d[k])) line[k] = d[k];
    for (const k of ['currency', 'incoterm', 'hs_code']) if (!blank(d[k])) line[k] = d[k].trim().toUpperCase();
    if (!blank(d.origin)) line.origin = d.origin;
    return api.post<Simulation>('/sourcing/tco/simulate', {
      supplier: d.supplier.trim(), category: d.category.trim(), material: blank(d.material) ? undefined : d.material.trim(), line,
      annual_qty: blank(d.annual_qty) ? undefined : d.annual_qty, on: blank(d.on) ? undefined : d.on,
    });
  }, { onSuccess: (r) => { setResult(r); setError(null); } });
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        What-if on one bid line under the tenant&apos;s SOURCING-TCO rule: price normalised to INR per base unit, freight, duty, packaging, carrying cost, quality cost and the value of the
        payment terms, each with its status. Leave freight, duty or packaging empty to see how the rule estimates them from the incoterm and the HS code.
      </p>
      <div className="grid gap-3 md:grid-cols-4">
        <Field label="Supplier code" required>{(id) => suppliers?.length
          ? <Select id={id} value={d.supplier} onChange={(e) => set({ supplier: e.target.value })} options={[{ value: '', label: 'Choose…' }, ...suppliers.map((s) => ({ value: s, label: s }))]} />
          : <Input id={id} value={d.supplier} onChange={(e) => set({ supplier: e.target.value })} />}</Field>
        <Field label="Category" required>{(id) => <Input id={id} value={d.category} onChange={(e) => set({ category: e.target.value.toUpperCase() })} />}</Field>
        <Field label="Material number" hint="Optional: safety stock and HS code come from it">{(id) => <Input id={id} value={d.material} onChange={(e) => set({ material: e.target.value })} />}</Field>
        <Field label="Annual quantity" hint="Optional">{(id) => <Input id={id} type="number" min="0" value={d.annual_qty} onChange={(e) => set({ annual_qty: e.target.value })} />}</Field>
        <Field label="Unit price (quoted currency)" required>{(id) => <Input id={id} type="number" min="0" step="any" value={d.unit_price} onChange={(e) => set({ unit_price: e.target.value })} />}</Field>
        <Field label="Currency">{(id) => <Input id={id} maxLength={3} value={d.currency} onChange={(e) => set({ currency: e.target.value.toUpperCase() })} />}</Field>
        <Field label="Incoterm">{(id) => <Input id={id} maxLength={10} value={d.incoterm} onChange={(e) => set({ incoterm: e.target.value.toUpperCase() })} placeholder="EXW, FCA, DAP…" />}</Field>
        <Field label="Origin">{(id) => <Select id={id} value={d.origin} onChange={(e) => set({ origin: e.target.value })} options={[{ value: '', label: 'From supplier country' }, { value: 'DOMESTIC', label: 'Domestic' }, { value: 'IMPORT', label: 'Import' }]} />}</Field>
        <Field label="Freight per unit" hint="Empty: estimated">{(id) => <Input id={id} type="number" min="0" step="any" value={d.freight} onChange={(e) => set({ freight: e.target.value })} />}</Field>
        <Field label="Duty per unit" hint="Empty: from HS code">{(id) => <Input id={id} type="number" min="0" step="any" value={d.duty} onChange={(e) => set({ duty: e.target.value })} />}</Field>
        <Field label="Packaging per unit">{(id) => <Input id={id} type="number" min="0" step="any" value={d.packaging} onChange={(e) => set({ packaging: e.target.value })} />}</Field>
        <Field label="HS code">{(id) => <Input id={id} maxLength={10} value={d.hs_code} onChange={(e) => set({ hs_code: e.target.value })} />}</Field>
        <Field label="Payment terms (days)" required>{(id) => <Input id={id} type="number" min="0" value={d.payment_terms_days} onChange={(e) => set({ payment_terms_days: e.target.value })} />}</Field>
        <Field label="Lead time (days)" required>{(id) => <Input id={id} type="number" min="0" value={d.lead_time_days} onChange={(e) => set({ lead_time_days: e.target.value })} />}</Field>
        <Field label="Minimum order quantity / month">{(id) => <Input id={id} type="number" min="0" value={d.moq} onChange={(e) => set({ moq: e.target.value })} />}</Field>
        <Field label="Base units per priced unit" hint="UoM factor, empty = 1">{(id) => <Input id={id} type="number" min="0" step="any" value={d.uom_factor} onChange={(e) => set({ uom_factor: e.target.value })} />}</Field>
        <Field label="Price includes tax">{(id) => <Select id={id} value={d.tax_included} onChange={(e) => set({ tax_included: e.target.value })} options={[{ value: 'false', label: 'No (price is net of tax)' }, { value: 'true', label: 'Yes (tax is stripped)' }]} />}</Field>
        <Field label="Tax rate (%)">{(id) => <Input id={id} type="number" min="0" max="50" step="any" value={d.tax_rate_pct} onChange={(e) => set({ tax_rate_pct: e.target.value })} />}</Field>
        <Field label="Pricing date" hint="Empty: today">{(id) => <Input id={id} type="date" value={d.on} onChange={(e) => set({ on: e.target.value })} />}</Field>
      </div>
      {problems.length > 0 && <p className="text-xs text-slate-500">Needed: {problems.join(', ')}.</p>}
      <div className="flex items-center gap-2">
        <Button variant="primary" disabled={problems.length > 0} busy={run.isPending} onClick={() => run.mutate(undefined, { onError: (e) => setError(e) })}>Simulate TCO</Button>
      </div>
      <ProblemBox error={error} />
      {result && (
        <div className="space-y-3" aria-live="polite">
          <div className="flex flex-wrap items-center gap-3 rounded-lg bg-slate-50 p-3 text-sm">
            <span>Rule <span className="font-mono text-xs">{result.rule}</span></span>
            <span>Price in INR: <span className="font-semibold tabular-nums">{inr(result.priceInr.minor)}</span>{result.priceInr.quotedMinor != null && result.priceInr.currency !== 'INR' && ` (quoted ${(result.priceInr.quotedMinor / 100).toFixed(2)} ${result.priceInr.currency})`}</span>
            <span>TCO: <span className="font-semibold tabular-nums">{inr(result.tcoMinor)}</span></span>
            {result.incomplete
              ? <span role="status" className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold uppercase text-red-800 ring-1 ring-inset ring-red-200">Incomplete: {result.missing.map(label).join(', ')} missing</span>
              : <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold uppercase text-emerald-800 ring-1 ring-inset ring-emerald-200">Complete</span>}
          </div>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_1fr]">
            <TcoStack parts={result.parts} totalMinor={result.tcoMinor} missing={result.missing} />
            <TraceTable trace={result.trace} />
          </div>
        </div>
      )}
    </div>
  );
}
