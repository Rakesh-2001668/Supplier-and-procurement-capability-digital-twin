'use client';

import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';
import { Button, Card, Field, Input, LinkButton, Loading, PageHeader, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { api, Paged } from '@/lib/pic/api';
import { date, inr, label, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { hasRole, isPositive, useSessionUser } from '../../invoices/_components';

type ContractType = 'SCHEDULING_AGREEMENT' | 'QUANTITY_CONTRACT' | 'VALUE_CONTRACT' | 'MASTER_AGREEMENT' | 'RATE_CARD' | 'SOW' | 'NDA';
type Template = { code: string; title: string; text: string };
type Jurisdiction = { code: string; name: string; seat: string; law: string };
type ListedContract = { number: string; type: string; status: string; supplier_code: string; title: string; valid_from: string; valid_to: string };
type Obligation = { party: string; description: string; dueAfterDays: number; kind?: string };
type Templates = { ruleSet: string; types: ContractType[]; frameworkTypes: string[]; templates: Record<string, Template[]>; obligations: Record<string, Obligation[]>;
  fallbacks: Record<string, string>; jurisdictions: Jurisdiction[]; categories?: string[] };
type Supplier = { code: string; legal_name: string; status: string; payment_terms: string | null; incoterms: string | null };
type Material = { number: string; description: string; base_uom: string };
type Org = { plants: { code: string; name: string }[]; companyCodes?: { code: string; name: string; active?: boolean }[] };
type Line = { material: string; description: string; plant: string; uom: string; target_qty: string; unit_price: string };
type Created = { number: string };

const TYPE_TEXT: Record<ContractType, string> = {
  SCHEDULING_AGREEMENT: 'Delivery schedules released against the agreement; index-linked pricing; ERS-eligible.',
  QUANTITY_CONTRACT: 'A fixed total quantity at fixed prices, released by purchase order.',
  VALUE_CONTRACT: 'A total value (typically services) consumed by purchase orders.',
  RATE_CARD: 'Unit rates per role or service, fixed for the term; orders draw on the rates.',
  SOW: 'A statement of work: scope, deliverables and milestones accepted one by one.',
  MASTER_AGREEMENT: 'Commercial terms only: no value, no quantities. Call-off contracts refer to it.',
  NDA: 'Confidentiality only: no value, no lines, nothing to consume.',
};
const CREATABLE: ContractType[] = ['SCHEDULING_AGREEMENT', 'QUANTITY_CONTRACT', 'VALUE_CONTRACT', 'RATE_CARD', 'SOW', 'MASTER_AGREEMENT', 'NDA'];
const RESETS = ['MONTHLY', 'QUARTERLY', 'HALF_YEARLY', 'ANNUAL'];
const FRAMEWORK: ContractType[] = ['MASTER_AGREEMENT', 'NDA'];

// An empty plant means "the first plant of the organisation" (resolved when the form is submitted), so no plant code is hard-coded.
const emptyLine = (plant = ''): Line => ({ material: '', description: '', plant, uom: 'EA', target_qty: '', unit_price: '' });

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
  const companyCodes = (org.data?.companyCodes ?? []).filter((c) => c.active !== false);
  const plantOf = (l: Line) => l.plant || plants[0]?.code || '';
  const contracts = useApi<Paged<ListedContract>>('/contracts?limit=200');

  // One key per form: a double-submit or network retry replays the same contract instead of creating two.
  const [idempotencyKey] = useState(() => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`));
  const [type, setType] = useState<ContractType>('SCHEDULING_AGREEMENT');
  const [f, setF] = useState({ supplier: '', title: '', valid_from: new Date().toISOString().slice(0, 10), valid_to: inOneYear(), payment_terms: 'N45',
    incoterms: 'FCA', over_pct: '5', under_pct: '5', price_pct: '0', index: 'LME_AL', index_base: '100.00', band_pct: '3', reset: 'QUARTERLY', company_code: '', category: '' });
  const [lines, setLines] = useState<Line[]>([emptyLine()]);
  const [invalid, setInvalid] = useState<string | null>(null);
  const [framework, setFramework] = useState('');
  const [jurisdiction, setJurisdiction] = useState('');
  const variant = useApi<{ jurisdictionClauses: Template[] }>(jurisdiction ? `/contract-templates?jurisdiction=${encodeURIComponent(jurisdiction)}` : null);
  const isFramework = FRAMEWORK.includes(type);

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

  const masters = (contracts.data?.items ?? []).filter((c) => c.type === 'MASTER_AGREEMENT' && ['ACTIVE', 'EXPIRING'].includes(c.status)
    && (!f.supplier.trim() || c.supplier_code.toUpperCase() === f.supplier.trim().toUpperCase()));

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!f.supplier.trim() || !f.title.trim() || !f.payment_terms.trim()) { setInvalid('Supplier, title and payment terms are required.'); return; }
    if (!f.valid_from || !f.valid_to || f.valid_to <= f.valid_from) { setInvalid('Valid to must be after valid from.'); return; }
    if (supplier?.status === 'BLOCKED') { setInvalid(`${supplier.code} is blocked and cannot be contracted.`); return; }
    const bad = isFramework ? -1 : lines.findIndex((l) => !l.description.trim() || !l.uom.trim() || !plantOf(l).trim() || l.uom.trim().length > 5 || !isPositive(l.target_qty) || !isPositive(l.unit_price));
    if (bad >= 0) { setInvalid(`Line ${(bad + 1) * 10}: description, plant, unit, a positive target quantity and unit price are required.`); return; }
    if (!isFramework && [f.over_pct, f.under_pct, f.price_pct].some((v) => v.trim() === '' || Number.isNaN(Number(v)) || Number(v) < 0 || Number(v) > 100)) {
      setInvalid('Tolerances must be percentages between 0 and 100.'); return;
    }
    const indexed = type === 'SCHEDULING_AGREEMENT';
    if (indexed && (!f.index.trim() || !isPositive(f.index_base) || f.band_pct.trim() === '' || Number.isNaN(Number(f.band_pct)) || Number(f.band_pct) < 0 || Number(f.band_pct) >= 100)) {
      setInvalid('A scheduling agreement needs the price index, its base value and the absorbed band % (0 up to 100).'); return;
    }
    setInvalid(null);
    create.mutate({
      type, title: f.title.trim(), supplier: f.supplier.trim().toUpperCase(), company_code: f.company_code || companyCodes[0]?.code || '1000',
      valid_from: f.valid_from, valid_to: f.valid_to, payment_terms: f.payment_terms.trim(), incoterms: f.incoterms.trim() || undefined,
      jurisdiction: jurisdiction || undefined, category: f.category.trim() || undefined, framework: !isFramework && framework ? framework : undefined,
      tolerances: { over_pct: f.over_pct.trim(), under_pct: f.under_pct.trim(), price_pct: f.price_pct.trim() },
      index_ref: indexed ? { index: f.index.trim().toUpperCase(), base: f.index_base.trim(), band_pct: f.band_pct.trim(), reset: f.reset } : undefined,
      lines: isFramework ? [] : lines.map((l) => ({
        material: l.material.trim() || undefined, description: l.description.trim(), plant: plantOf(l).trim(), uom: l.uom.trim().toUpperCase(),
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
          Creating contracts needs the contract manager role. You can still preview the templates.
        </p>
      )}

      <form onSubmit={submit} className="grid gap-5 lg:grid-cols-5">
        <div className="space-y-5 lg:col-span-3">
          <Card title="Contract type">
            {templates.isLoading ? <Loading /> : templates.error || !templates.data ? <ProblemBox error={templates.error} /> : (
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3" role="radiogroup" aria-label="Contract type">
                {templates.data.types.filter((t) => CREATABLE.includes(t)).map((t) => (
                  <button key={t} type="button" role="radio" aria-checked={type === t} onClick={() => { setType(t); if (FRAMEWORK.includes(t)) setFramework(''); }}
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
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {companyCodes.length > 1 && (
                <Field label="Company code">
                  {(id) => <Select id={id} value={f.company_code || companyCodes[0].code} onChange={(e) => setF((x) => ({ ...x, company_code: e.target.value }))}
                    options={companyCodes.map((c) => ({ value: c.code, label: `${c.code} · ${c.name}` }))} />}
                </Field>
              )}
              <Field label="Category (clause overlay)" hint={templates.data?.categories?.length ? 'Adds the category clauses of the playbook' : 'The playbook has no category clauses yet'}>
                {(id) => (
                  <Select id={id} value={f.category} onChange={(e) => setF((x) => ({ ...x, category: e.target.value }))}
                    options={[{ value: '', label: 'No category overlay' }, ...(templates.data?.categories ?? []).map((c) => ({ value: c, label: label(c) }))]} />
                )}
              </Field>
              <Field label="Governing law and forum" hint="Adds the clause-library variant: governing law, dispute resolution, stamp duty, personal data">
                {(id) => (
                  <Select id={id} value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)}
                    options={[{ value: '', label: 'Playbook default (no variant)' }, ...(templates.data?.jurisdictions ?? []).map((j) => ({ value: j.code, label: `${j.code} · ${j.name} (${j.seat})` }))]} />
                )}
              </Field>
              {!isFramework && (
                <Field label="Framework (master agreement)" hint={masters.length ? 'Live master agreements of this supplier; the period must lie inside the master agreement' : 'No live master agreement for this supplier'}>
                  {(id) => (
                    <Select id={id} value={framework} onChange={(e) => setFramework(e.target.value)}
                      options={[{ value: '', label: 'None – stand-alone contract' }, ...masters.map((m) => ({ value: m.number, label: `${m.number} · ${date(m.valid_from)} – ${date(m.valid_to)}` }))]} />
                  )}
                </Field>
              )}
            </div>
            {!isFramework && <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <Field label="Over-delivery tolerance %">{(id) => <Input id={id} inputMode="decimal" value={f.over_pct} onChange={set('over_pct')} />}</Field>
              <Field label="Under-delivery tolerance %">{(id) => <Input id={id} inputMode="decimal" value={f.under_pct} onChange={set('under_pct')} />}</Field>
              <Field label="Price tolerance %">{(id) => <Input id={id} inputMode="decimal" value={f.price_pct} onChange={set('price_pct')} />}</Field>
            </div>}
            {type === 'SCHEDULING_AGREEMENT' && (
              <div className="mt-3 grid gap-3 sm:grid-cols-4">
                <Field label="Price index (required)">{(id) => <Input id={id} value={f.index} onChange={set('index')} placeholder="e.g. LME_AL" />}</Field>
                <Field label="Index base value">{(id) => <Input id={id} inputMode="decimal" value={f.index_base} onChange={set('index_base')} />}</Field>
                <Field label="Band absorbed by supplier ±%">{(id) => <Input id={id} inputMode="decimal" value={f.band_pct} onChange={set('band_pct')} />}</Field>
                <Field label="Reset">{(id) => <Select id={id} value={f.reset} onChange={set('reset')} options={RESETS.map((r) => ({ value: r, label: label(r) }))} />}</Field>
              </div>
            )}
          </Card>

          {!isFramework && <Card title="Lines" actions={<Button type="button" onClick={() => setLines((ls) => [...ls, emptyLine(plantOf(ls[ls.length - 1] ?? emptyLine()))])}>Add line</Button>}>
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
                        ? <Select id={id} value={plantOf(l)} onChange={(e) => updateLine(i, { plant: e.target.value })} options={plants.map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))} />
                        : <Input id={id} required value={l.plant} onChange={(e) => updateLine(i, { plant: e.target.value })} />}
                    </Field>
                    <Field label="Unit" hint="At most 5 characters">{(id) => <Input id={id} required maxLength={5} value={l.uom} onChange={(e) => updateLine(i, { uom: e.target.value })} />}</Field>
                    <Field label="Target quantity">{(id) => <Input id={id} required inputMode="decimal" value={l.target_qty} onChange={(e) => updateLine(i, { target_qty: e.target.value })} />}</Field>
                    <Field label="Unit price (₹)" hint={isPositive(l.unit_price) && isPositive(l.target_qty) ? `Line value ${inr(Number(l.target_qty) * rupeesToMinor(l.unit_price))}` : undefined}>
                      {(id) => <Input id={id} required inputMode="decimal" value={l.unit_price} onChange={(e) => updateLine(i, { unit_price: e.target.value })} />}
                    </Field>
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-3 text-right text-sm">Target value <span className="font-semibold tabular-nums">{inr(Math.round(targetValue))}</span></p>
          </Card>}
          {isFramework && <p role="note" className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-700">
            A {label(type).toLowerCase()} carries no lines, prices or value and nothing is consumed against it. Rebates (contract page) and call-off contracts attach to it later.</p>}

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
                {jurisdiction && (
                  <div className="rounded-lg bg-slate-50 p-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Governing-law variant · {jurisdiction}</p>
                    <p className="text-xs text-slate-500">Replaces or adds these clauses. The wording is a starting point that Legal reviews.</p>
                    {variant.isLoading ? <Loading /> : variant.error ? <ProblemBox error={variant.error} /> : (
                      <ol className="mt-2 space-y-2">
                        {(variant.data?.jurisdictionClauses ?? []).map((c) => (
                          <li key={c.code} className="text-sm"><p className="font-medium"><span className="font-mono text-[11px] text-slate-500">{c.code}</span> {c.title}</p><p className="text-slate-700">{c.text}</p></li>
                        ))}
                      </ol>
                    )}
                  </div>
                )}
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Obligations created</p>
                  <ul className="mt-1 divide-y divide-slate-100 text-sm">
                    {(templates.data.obligations[type] ?? []).map((o) => (
                      <li key={o.description} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                        <span><StatusChip status={o.party} /> {o.kind === 'MILESTONE' ? <span className="mr-1 text-[11px] font-semibold uppercase text-slate-500">milestone</span> : null}{o.description}</span>
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
