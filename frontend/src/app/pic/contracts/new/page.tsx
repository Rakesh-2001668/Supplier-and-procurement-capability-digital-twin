'use client';

import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';
import { Button, Card, Field, Input, LinkButton, Loading, PageHeader, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { api, Paged } from '@/lib/pic/api';
import { inr, label, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { hasRole, isPositive, useSessionUser } from '../../invoices/_components';

type ContractType = 'SCHEDULING_AGREEMENT' | 'QUANTITY_CONTRACT' | 'VALUE_CONTRACT';
type Template = { code: string; title: string; text: string };
type Obligation = { party: string; description: string; dueAfterDays: number };
type Templates = { ruleSet: string; types: ContractType[]; templates: Record<string, Template[]>; obligations: Record<string, Obligation[]>;
  fallbacks: Record<string, string> };
type Supplier = { code: string; legal_name: string; status: string; payment_terms: string | null; incoterms: string | null };
type Material = { number: string; description: string; base_uom: string };
type Org = { plants: { code: string; name: string }[] };
type Line = { material: string; description: string; plant: string; uom: string; target_qty: string; unit_price: string };
type Created = { number: string };

const TYPE_TEXT: Record<ContractType, string> = {
  SCHEDULING_AGREEMENT: 'Delivery schedules released against the agreement; index-linked pricing; ERS-eligible.',
  QUANTITY_CONTRACT: 'A fixed total quantity at fixed prices, released by purchase order.',
  VALUE_CONTRACT: 'A total value (typically services or rate cards) consumed by purchase orders.',
};

const emptyLine = (plant = 'P100'): Line => ({ material: '', description: '', plant, uom: 'EA', target_qty: '', unit_price: '' });

function inOneYear() {
  const d = new Date();
  d.setFullYear(d.getFullYear() + 1);
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

export default function NewContract() {
  const router = useRouter();
  const user = useSessionUser();
  const canCreate = hasRole(user, 'CONTRACT_MANAGER');
  const templates = useApi<Templates>('/contract-templates');
  const suppliers = useApi<Paged<Supplier>>('/suppliers?limit=200');
  const materials = useApi<Paged<Material>>('/materials?limit=200');
  const org = useApi<Org>('/admin/organisation');
  const plants = org.data?.plants ?? [];

  // One key per form: a double-submit or network retry replays the same contract instead of creating two.
  const [idempotencyKey] = useState(() => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`));
  const [type, setType] = useState<ContractType>('SCHEDULING_AGREEMENT');
  const [f, setF] = useState({ supplier: '', title: '', valid_from: new Date().toISOString().slice(0, 10), valid_to: inOneYear(), payment_terms: 'N45',
    incoterms: 'FCA', over_pct: '5', under_pct: '5', price_pct: '0', index: 'LME_AL', index_base: '100.00', band_pct: '3' });
  const [lines, setLines] = useState<Line[]>([emptyLine()]);
  const [invalid, setInvalid] = useState<string | null>(null);

  const supplier = suppliers.data?.items.find((s) => s.code.toUpperCase() === f.supplier.trim().toUpperCase());
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));
  const updateLine = (i: number, patch: Partial<Line>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const targetValue = lines.reduce((s, l) => s + (isPositive(l.target_qty) && isPositive(l.unit_price) ? Number(l.target_qty) * rupeesToMinor(l.unit_price) : 0), 0);

  const create = useCommand((body: Record<string, unknown>) => api.post<Created>('/contracts', body, { idempotencyKey }), {
    success: (c) => `Contract ${c.number} drafted`, onSuccess: (c) => router.push(`/pic/contracts/${encodeURIComponent(c.number)}`),
  });

  function pickSupplier(code: string) {
    const s = suppliers.data?.items.find((x) => x.code.toUpperCase() === code.trim().toUpperCase());
    setF((x) => ({ ...x, supplier: code, payment_terms: s?.payment_terms ?? x.payment_terms, incoterms: s?.incoterms ?? x.incoterms }));
  }

  function pickMaterial(i: number, number: string) {
    const m = materials.data?.items.find((x) => x.number === number.trim());
    updateLine(i, m ? { material: number, description: lines[i].description || m.description, uom: m.base_uom } : { material: number });
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!f.supplier.trim() || !f.title.trim() || !f.payment_terms.trim()) { setInvalid('Supplier, title and payment terms are required.'); return; }
    if (!f.valid_from || !f.valid_to || f.valid_to <= f.valid_from) { setInvalid('Valid to must be after valid from.'); return; }
    if (supplier?.status === 'BLOCKED') { setInvalid(`${supplier.code} is blocked and cannot be contracted.`); return; }
    const bad = lines.findIndex((l) => !l.description.trim() || !l.uom.trim() || !l.plant.trim() || !isPositive(l.target_qty) || !isPositive(l.unit_price));
    if (bad >= 0) { setInvalid(`Line ${(bad + 1) * 10}: description, plant, unit, a positive target quantity and unit price are required.`); return; }
    if ([f.over_pct, f.under_pct, f.price_pct].some((v) => v.trim() === '' || Number.isNaN(Number(v)) || Number(v) < 0)) {
      setInvalid('Tolerances must be zero or positive percentages.'); return;
    }
    const indexed = type === 'SCHEDULING_AGREEMENT';
    if (indexed && (!f.index.trim() || !isPositive(f.index_base) || f.band_pct.trim() === '' || Number.isNaN(Number(f.band_pct)))) {
      setInvalid('A scheduling agreement needs the price index, its base value and the absorbed band %.'); return;
    }
    setInvalid(null);
    create.mutate({
      type, title: f.title.trim(), supplier: f.supplier.trim().toUpperCase(), company_code: '1000', valid_from: f.valid_from, valid_to: f.valid_to,
      payment_terms: f.payment_terms.trim(), incoterms: f.incoterms.trim() || undefined,
      tolerances: { over_pct: f.over_pct.trim(), under_pct: f.under_pct.trim(), price_pct: f.price_pct.trim() },
      index_ref: indexed ? { index: f.index.trim().toUpperCase(), base: f.index_base.trim(), band_pct: f.band_pct.trim(), reset: 'QUARTERLY' } : undefined,
      lines: lines.map((l) => ({
        material: l.material.trim() || undefined, description: l.description.trim(), plant: l.plant.trim(), uom: l.uom.trim().toUpperCase(),
        target_qty: l.target_qty.trim(), unit_price_minor: rupeesToMinor(l.unit_price),
      })),
    });
  }

  const fill = (text: string) => text.replace(/\{terms\}/g, f.payment_terms || '…').replace(/\{incoterms\}/g, f.incoterms || '')
    .replace(/\{supplier\}/g, supplier?.legal_name ?? (f.supplier || 'the supplier')).replace(/\{band\}/g, type === 'SCHEDULING_AGREEMENT' ? f.band_pct || '…' : '…')
    .replace(/\{over\}/g, f.over_pct || '0').replace(/\{under\}/g, f.under_pct || '0');

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="CLM-01 · Manual contract" title="New contract"
        subtitle="Draft a contract without a sourcing award. Playbook clauses and obligations for the chosen type are added automatically; the draft then goes through AI review, approval and e-signature like any other."
        actions={<LinkButton href="/pic/contracts">Back to contracts</LinkButton>} />

      {user && !canCreate && (
        <p role="note" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
          Creating contracts needs the contract manager role (contract.manager@axion.example). You can still preview the templates.
        </p>
      )}

      <form onSubmit={submit} className="grid gap-5 lg:grid-cols-5">
        <div className="space-y-5 lg:col-span-3">
          <Card title="Contract type">
            {templates.isLoading ? <Loading /> : templates.error || !templates.data ? <ProblemBox error={templates.error} /> : (
              <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Contract type">
                {templates.data.types.map((t) => (
                  <button key={t} type="button" role="radio" aria-checked={type === t} onClick={() => setType(t)}
                    className={`rounded-lg border px-3 py-2 text-left text-sm ${type === t ? 'border-[#1A56DB] bg-blue-50 ring-1 ring-[#1A56DB]' : 'border-slate-200 hover:bg-slate-50'}`}>
                    <span className="font-semibold">{label(t)}</span>
                    <span className="mt-0.5 block text-xs text-slate-600">{TYPE_TEXT[t] ?? ''}</span>
                  </button>
                ))}
              </div>
            )}
          </Card>

          <Card title="Header">
            <datalist id="supplier-codes">{suppliers.data?.items.map((s) => <option key={s.code} value={s.code}>{s.legal_name}</option>)}</datalist>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Supplier code (required)" hint={supplier ? `${supplier.legal_name} · ${label(supplier.status)}` : f.supplier ? 'Not in the first 200 suppliers; the API will check it' : undefined}>
                {(id) => <Input id={id} list="supplier-codes" required value={f.supplier} onChange={(e) => pickSupplier(e.target.value)} placeholder="e.g. TF001" />}
              </Field>
              <Field label="Title (required)">{(id) => <Input id={id} required value={f.title} onChange={set('title')} placeholder="e.g. Machined brackets 2027 – Trichy Forge" />}</Field>
              <Field label="Valid from (required)">{(id) => <Input id={id} type="date" required value={f.valid_from} onChange={set('valid_from')} />}</Field>
              <Field label="Valid to (required)">{(id) => <Input id={id} type="date" required value={f.valid_to} onChange={set('valid_to')} />}</Field>
              <Field label="Payment terms (required)" hint="e.g. N45, or 2/10 N45 for an early-payment discount">{(id) => <Input id={id} required value={f.payment_terms} onChange={set('payment_terms')} />}</Field>
              <Field label="Incoterms">{(id) => <Input id={id} value={f.incoterms} onChange={set('incoterms')} placeholder="e.g. FCA Hosur" />}</Field>
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <Field label="Over-delivery tolerance %">{(id) => <Input id={id} inputMode="decimal" value={f.over_pct} onChange={set('over_pct')} />}</Field>
              <Field label="Under-delivery tolerance %">{(id) => <Input id={id} inputMode="decimal" value={f.under_pct} onChange={set('under_pct')} />}</Field>
              <Field label="Price tolerance %">{(id) => <Input id={id} inputMode="decimal" value={f.price_pct} onChange={set('price_pct')} />}</Field>
            </div>
            {type === 'SCHEDULING_AGREEMENT' && (
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <Field label="Price index (required)" hint="Reset quarterly">{(id) => <Input id={id} value={f.index} onChange={set('index')} placeholder="e.g. LME_AL" />}</Field>
                <Field label="Index base value">{(id) => <Input id={id} inputMode="decimal" value={f.index_base} onChange={set('index_base')} />}</Field>
                <Field label="Band absorbed by supplier ±%">{(id) => <Input id={id} inputMode="decimal" value={f.band_pct} onChange={set('band_pct')} />}</Field>
              </div>
            )}
          </Card>

          <Card title="Lines" actions={<Button type="button" onClick={() => setLines((ls) => [...ls, emptyLine(plants[0]?.code)])}>Add line</Button>}>
            <datalist id="material-numbers">{materials.data?.items.map((m) => <option key={m.number} value={m.number}>{m.description}</option>)}</datalist>
            <div className="space-y-3">
              {lines.map((l, i) => (
                <div key={i} className="rounded-lg border border-slate-200 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-sm font-semibold">Line {(i + 1) * 10}</p>
                    {lines.length > 1 && <Button type="button" variant="ghost" onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>Remove</Button>}
                  </div>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <Field label="Material (optional)">{(id) => <Input id={id} list="material-numbers" value={l.material} onChange={(e) => pickMaterial(i, e.target.value)} />}</Field>
                    <div className="sm:col-span-2">
                      <Field label="Description (required)">{(id) => <Input id={id} required value={l.description} onChange={(e) => updateLine(i, { description: e.target.value })} />}</Field>
                    </div>
                    <Field label="Plant">
                      {(id) => plants.length
                        ? <Select id={id} value={l.plant} onChange={(e) => updateLine(i, { plant: e.target.value })} options={plants.map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))} />
                        : <Input id={id} value={l.plant} onChange={(e) => updateLine(i, { plant: e.target.value })} />}
                    </Field>
                    <Field label="Unit">{(id) => <Input id={id} required value={l.uom} onChange={(e) => updateLine(i, { uom: e.target.value })} />}</Field>
                    <Field label="Target quantity">{(id) => <Input id={id} required inputMode="decimal" value={l.target_qty} onChange={(e) => updateLine(i, { target_qty: e.target.value })} />}</Field>
                    <Field label="Unit price (₹)" hint={isPositive(l.unit_price) && isPositive(l.target_qty) ? `Line value ${inr(Number(l.target_qty) * rupeesToMinor(l.unit_price))}` : undefined}>
                      {(id) => <Input id={id} required inputMode="decimal" value={l.unit_price} onChange={(e) => updateLine(i, { unit_price: e.target.value })} />}
                    </Field>
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-3 text-right text-sm">Target value <span className="font-semibold tabular-nums">{inr(Math.round(targetValue))}</span></p>
          </Card>

          {invalid && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-900">{invalid}</p>}
          <ProblemBox error={create.error} />
          <div className="flex justify-end gap-2">
            <LinkButton href="/pic/contracts">Cancel</LinkButton>
            <Button type="submit" variant="primary" disabled={!canCreate} busy={create.isPending}>Create draft</Button>
          </div>
        </div>

        <div className="space-y-5 lg:col-span-2">
          <Card title={<span>Playbook preview · {label(type)}</span>}>
            {templates.data ? (
              <div className="space-y-4">
                <p className="text-xs text-slate-500">Rule set <span className="font-mono">{templates.data.ruleSet}</span>. Clauses start at the standard position and can be redlined later.</p>
                <ol className="space-y-3">
                  {(templates.data.templates[type] ?? []).map((c) => (
                    <li key={c.code} className="text-sm">
                      <p className="flex items-center gap-2 font-medium"><span className="font-mono text-[11px] text-slate-500">{c.code}</span>{c.title}</p>
                      <p className="mt-0.5 text-slate-700">{fill(c.text)}</p>
                      {templates.data?.fallbacks[c.code] && <p className="mt-0.5 text-xs text-slate-500">Fallback: {templates.data.fallbacks[c.code]}</p>}
                    </li>
                  ))}
                </ol>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Obligations created</p>
                  <ul className="mt-1 divide-y divide-slate-100 text-sm">
                    {(templates.data.obligations[type] ?? []).map((o) => (
                      <li key={o.description} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                        <span><StatusChip status={o.party} /> {o.description}</span>
                        <span className="text-xs text-slate-500">due {o.dueAfterDays} days after start</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : <Loading />}
          </Card>
        </div>
      </form>
    </div>
  );
}
