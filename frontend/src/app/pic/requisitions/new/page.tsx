'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { FormEvent, Suspense, useState } from 'react';
import { Button, Card, Empty, Field, Input, Loading, PageHeader, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { inr, label, qty as fmtQty, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { AccountAssignment, NEEDS_ACCOUNT, PolicyProblem, PURCHASE_TYPES, Reference, Requisition, SubmitPanel, useReference } from '../_components';
import { PunchOut } from './punchout';

type ContractHit = { channel: 'CONTRACT'; contract: string; line: number; description: string; unitPriceMinor: number | null; score: number };
type CatalogueHit = { channel: 'CATALOGUE'; id: string; supplierPartNo: string | null; description: string; unitPriceMinor: number; uom: string; score: number };
type MaterialHit = { channel: 'MATERIAL'; material: string; description: string; uom: string; score: number };
type Search = {
  query: string; searchOrder: string[]; recommendedChannel: string; freeTextAllowed: boolean; hint: string | null;
  results: { contract: ContractHit[]; catalogue: CatalogueHit[]; material: MaterialHit[] };
};
type MaterialRow = { number: string; material_group: string | null; category: string | null };

type ItemType = 'MATERIAL' | 'CATALOGUE' | 'FREE_TEXT';
type DraftLine = {
  key: string; item_type: ItemType; source: string; material?: string; catalogue_item_id?: string;
  description: string; material_group: string; category: string; purchase_type: string; qty: string; uom: string;
  price: string; priceFixed: boolean; aat: string; aac: string; need_date: string; quotes: string; reusable: boolean; mpn: string;
};

const ORIGINS = ['MANUAL', 'PROJECT', 'CATALOGUE'];
const CHANNEL_TITLE: Record<string, string> = {
  CONTRACT: '1 · Contract items', CATALOGUE: '2 · Catalogue items', MATERIAL: '3 · Material master', FREE_TEXT: '4 · Free text',
};

function inDays(n: number) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}
let seq = 0;
const newKey = () => `l${++seq}`;
const minorToRupees = (m: number | null | undefined) => (m == null ? '' : String(m / 100));

export default function NewRequisitionPage() {
  // useSearchParams (punch-out return) needs a Suspense boundary for prerendering.
  return <Suspense fallback={<Loading />}><NewRequisition /></Suspense>;
}

function NewRequisition() {
  const params = useSearchParams();
  const ref = useReference();
  const materialsMaster = useApi<{ items: MaterialRow[] }>('/materials?limit=200');
  const [plant, setPlant] = useState('');
  const [purposeCode, setPurposeCode] = useState('');
  const [purposeText, setPurposeText] = useState('');
  const [origin, setOrigin] = useState('MANUAL');
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [created, setCreated] = useState<Requisition | null>(null);

  const reference = ref.data;
  const effectivePlant = plant || reference?.plants[0]?.code || '';
  const groups = Array.from(new Set((materialsMaster.data?.items ?? []).map((m) => m.material_group).filter(Boolean))) as string[];
  const categories = Array.from(new Set([...(materialsMaster.data?.items ?? []).map((m) => m.category), ...(reference?.catalogue ?? []).map((c) => c.category)]
    .filter(Boolean))) as string[];

  const create = useCommand(() => api.post<Requisition>('/requisitions', {
    origin, plant: effectivePlant, purpose_code: purposeCode.trim(), purpose_text: purposeText.trim() || undefined,
    lines: lines.map((l) => ({
      item_type: l.item_type, purchase_type: l.purchase_type,
      material: l.item_type === 'MATERIAL' ? l.material : undefined,
      catalogue_item_id: l.item_type === 'CATALOGUE' ? l.catalogue_item_id : undefined,
      description: l.item_type === 'FREE_TEXT' ? l.description.trim() : undefined,
      material_group: l.item_type === 'FREE_TEXT' ? l.material_group.trim() : undefined,
      category: l.item_type === 'FREE_TEXT' ? (l.category.trim() || undefined) : undefined,
      qty: l.qty, uom: l.uom || undefined,
      price_est_minor: l.priceFixed ? undefined : rupeesToMinor(l.price),
      account_assignment_type: l.aat || undefined, account_assignment_code: l.aac || undefined,
      need_date: l.need_date,
      quotes_attached: l.item_type === 'FREE_TEXT' ? Number(l.quotes || 0) : 0,
      reusable: l.item_type === 'FREE_TEXT' ? l.reusable : false,
      mpn: l.item_type === 'FREE_TEXT' && l.reusable && l.mpn.trim() ? l.mpn.trim() : undefined,
    })),
  }), { success: (r) => `${r.number} created as draft`, onSuccess: (r) => setCreated(r) });

  const addLine = (line: Partial<DraftLine> & Pick<DraftLine, 'item_type' | 'source'>) =>
    setLines((prev) => [...prev, {
      key: newKey(), description: '', material_group: '', category: '', purchase_type: 'NON_STOCK', qty: '1', uom: 'EA', price: '',
      priceFixed: false, aat: '', aac: '', need_date: inDays(14), quotes: '0', reusable: false, mpn: '', ...line,
    }]);
  const update = (key: string, patch: Partial<DraftLine>) => setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  const remove = (key: string) => setLines((prev) => prev.filter((l) => l.key !== key));

  const addMaterial = (number: string, source: string) => {
    const m = reference?.materials.find((x) => x.number === number);
    if (!m) return;
    addLine({ item_type: 'MATERIAL', source, material: m.number, description: m.description, uom: m.uom,
      purchase_type: m.type === 'STOCK' ? 'STOCK' : 'NON_STOCK', price: minorToRupees(m.standardPriceMinor) });
  };
  const addCatalogue = (id: string, description: string, priceMinor: number, uom: string) => {
    const item = reference?.catalogue.find((c) => c.id === id);
    addLine({ item_type: 'CATALOGUE', source: 'Catalogue', catalogue_item_id: id, description, uom, price: minorToRupees(priceMinor), priceFixed: true,
      purchase_type: (item?.category ?? '').includes('SERVICE') ? 'SERVICE' : 'NON_STOCK' });
  };

  const validate = (): string[] => {
    const out: string[] = [];
    if (!effectivePlant) out.push('Choose a plant.');
    if (!purposeCode.trim()) out.push('Purpose code is mandatory (P01).');
    if (!lines.length) out.push('Add at least one line.');
    lines.forEach((l, i) => {
      const n = `Line ${(i + 1) * 10}`;
      if (!(Number(l.qty) > 0)) out.push(`${n}: quantity must be greater than zero.`);
      if (!l.need_date) out.push(`${n}: need date is required.`);
      if (!l.priceFixed && !(Number(l.price) > 0)) out.push(`${n}: an estimated unit price is required.`);
      if (l.item_type === 'FREE_TEXT' && !l.description.trim()) out.push(`${n}: description is required.`);
      if (l.item_type === 'FREE_TEXT' && !l.material_group.trim()) out.push(`${n}: material group is required (P04).`);
      if (NEEDS_ACCOUNT.includes(l.purchase_type) && (!l.aat || !l.aac)) out.push(`${n}: ${label(l.purchase_type).toLowerCase()} purchases need an account assignment.`);
    });
    return out;
  };

  const onCreate = (e: FormEvent) => {
    e.preventDefault();
    const v = validate();
    setErrors(v);
    if (!v.length) create.mutate();
  };

  const reset = () => {
    setCreated(null); setLines([]); setPurposeCode(''); setPurposeText(''); setErrors([]); create.reset();
  };

  const total = lines.reduce((sum, l) => sum + (Number(l.qty) || 0) * (Number(l.price) || 0), 0);

  if (ref.isLoading) return <Loading />;
  if (ref.error || !reference) return <ProblemBox error={ref.error} />;

  if (created) {
    return (
      <div className="space-y-5">
        <PageHeader eyebrow="REQ-01 / REQ-02 · Guided buying" title={<>Requisition {created.number} created</>}
          subtitle="The draft is saved. Submit it to run the policy and budget checks and route it for approval." />
        <Card title={<span className="flex items-center gap-2">{created.number} <StatusChip status={created.status} /></span>}
          actions={<><Link href={`/pic/requisitions/${created.number}`} className="text-sm font-medium text-[#1A56DB] hover:underline">Open requisition →</Link>
            <Button variant="ghost" onClick={reset}>Start another</Button></>}>
          <p className="mb-4 text-sm text-slate-700">{created.lines?.length ?? lines.length} line(s) · total {inr(created.total_minor)} · purpose {created.purpose_code}</p>
          <SubmitPanel pr={created} />
        </Card>
      </div>
    );
  }

  return (
    <form onSubmit={onCreate} className="space-y-5" noValidate>
      <PageHeader eyebrow="REQ-01 / REQ-02 · Guided buying" title="New requisition"
        subtitle="Search first: contract items, then catalogue, then material master. Free text is the last resort and must carry a material group and account assignment." />

      <Card title="Header">
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Plant *">{(id) => (
            <Select id={id} value={effectivePlant} onChange={(e) => setPlant(e.target.value)}
              options={reference.plants.map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))} />
          )}</Field>
          <Field label="Purpose code *" hint="Mandatory (P01), e.g. MAINTENANCE">{(id) => (
            <Input id={id} required value={purposeCode} onChange={(e) => setPurposeCode(e.target.value.toUpperCase())} />
          )}</Field>
          <Field label="Origin">{(id) => (
            <Select id={id} value={origin} onChange={(e) => setOrigin(e.target.value)} options={ORIGINS.map((o) => ({ value: o, label: label(o) }))} />
          )}</Field>
          <Field label="Purpose text">{(id) => <Input id={id} value={purposeText} onChange={(e) => setPurposeText(e.target.value)} />}</Field>
        </div>
      </Card>

      <PunchOut plant={effectivePlant} purposeCode={purposeCode.trim()} purposeText={purposeText.trim()} draftLines={lines.length}
        cookie={params.get('punchout')} error={params.get('punchoutError')} onConverted={(r) => setCreated(r)} />

      <GuidedSearch plant={effectivePlant} reference={reference}
        onMaterial={(n, source) => addMaterial(n, source)} onCatalogue={addCatalogue}
        onFreeText={(description) => addLine({ item_type: 'FREE_TEXT', source: 'Free text', description })} />

      <Card title={`Lines (${lines.length})`} actions={<MaterialPicker reference={reference} onAdd={(n) => addMaterial(n, 'Material master')} />}>
        {!lines.length ? <Empty title="No lines yet" hint="Search above and add a contract, catalogue, material or free-text line." /> : (
          <div className="space-y-3">
            {lines.map((l, i) => (
              <LineEditor key={l.key} lineNo={(i + 1) * 10} line={l} reference={reference}
                onChange={(patch) => update(l.key, patch)} onRemove={() => remove(l.key)} />
            ))}
            <p className="text-right text-sm">Estimated total <span className="font-semibold tabular-nums">{inr(Math.round(total * 100))}</span></p>
          </div>
        )}
      </Card>

      {errors.length > 0 && (
        <div role="alert" className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p className="font-semibold">Please fix before creating</p>
          <ul className="mt-1 list-disc pl-5">{errors.map((e) => <li key={e}>{e}</li>)}</ul>
        </div>
      )}
      <PolicyProblem error={create.error} />
      <datalist id="pic-material-groups">{groups.map((g) => <option key={g} value={g} />)}</datalist>
      <datalist id="pic-categories">{categories.map((c) => <option key={c} value={c} />)}</datalist>
      <div className="flex justify-end gap-2">
        <Link href="/pic/requisitions" className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-50">Cancel</Link>
        <Button type="submit" variant="primary" busy={create.isPending}>Create requisition</Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- REQ-01 guided search (contract → catalogue → material → free text)
function GuidedSearch({ plant, reference, onMaterial, onCatalogue, onFreeText }: {
  plant: string; reference: Reference;
  onMaterial: (number: string, source: string) => void;
  onCatalogue: (id: string, description: string, priceMinor: number, uom: string) => void;
  onFreeText: (description: string) => void;
}) {
  const [text, setText] = useState('');
  const [q, setQ] = useState('');
  const search = useApi<Search>(q ? `/guided-buying/search?q=${encodeURIComponent(q)}${plant ? `&plant=${encodeURIComponent(plant)}` : ''}` : null);
  const data = search.data;
  const go = () => setQ(text.trim());

  const materialFor = (description: string) => reference.materials.find((m) => m.description.toLowerCase() === description.toLowerCase());

  const groupBody = (channel: string) => {
    if (!data) return null;
    if (channel === 'CONTRACT') {
      return data.results.contract.length ? data.results.contract.map((h) => {
        const m = materialFor(h.description);
        return (
          <Hit key={`${h.contract}-${h.line}`} title={h.description} meta={`Contract ${h.contract} line ${h.line} · ${h.unitPriceMinor != null ? inr(h.unitPriceMinor) : 'price per validity period'} · match ${Math.round(h.score * 100)}%`}
            action={m ? <Button type="button" onClick={() => onMaterial(m.number, `Contract ${h.contract} line ${h.line}`)}>Add {m.number}</Button>
              : <span className="text-xs text-slate-500">No material master for this contract item</span>} />
        );
      }) : <NoHits />;
    }
    if (channel === 'CATALOGUE') {
      return data.results.catalogue.length ? data.results.catalogue.map((h) => (
        <Hit key={h.id} title={h.description} meta={`${inr(h.unitPriceMinor)} / ${h.uom}${h.supplierPartNo ? ` · part ${h.supplierPartNo}` : ''} · match ${Math.round(h.score * 100)}%`}
          action={<Button type="button" onClick={() => onCatalogue(h.id, h.description, h.unitPriceMinor, h.uom)}>Add</Button>} />
      )) : <NoHits />;
    }
    if (channel === 'MATERIAL') {
      return data.results.material.length ? data.results.material.map((h) => (
        <Hit key={h.material} title={`${h.material} · ${h.description}`} meta={`${h.uom} · match ${Math.round(h.score * 100)}%`}
          action={<Button type="button" onClick={() => onMaterial(h.material, 'Material master')}>Add</Button>} />
      )) : <NoHits />;
    }
    return (
      <Hit title={`“${data.query}” as free text`} meta={data.freeTextAllowed ? 'Nothing matched in contracts, catalogue or material master.' : 'A structured result exists above; free text needs a reason to bypass it.'}
        action={<Button type="button" variant={data.freeTextAllowed ? 'primary' : 'secondary'} onClick={() => onFreeText(data.query)}>
          {data.freeTextAllowed ? 'Add free-text line' : 'Add free text anyway'}</Button>} />
    );
  };

  return (
    <Card title="Find what you need (REQ-01)">
      <div className="flex flex-col gap-2 md:flex-row md:items-end">
        <div className="md:flex-1">
          <Field label="Search contracts, catalogue and materials">{(id) => (
            <Input id={id} type="search" value={text} placeholder="e.g. housing, maintenance visit, fixture"
              onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); go(); } }} />
          )}</Field>
        </div>
        <Button type="button" variant="primary" onClick={go} disabled={!text.trim()} busy={search.isFetching}>Search</Button>
      </div>
      {search.error && <div className="mt-3"><ProblemBox error={search.error} /></div>}
      {data && (
        <div className="mt-4 space-y-4">
          {data.hint ? (
            <p role="status" className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">
              <span className="font-semibold">Recommended: {label(data.recommendedChannel)}.</span> {data.hint}
            </p>
          ) : (
            <p role="status" className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">No contract, catalogue or material match — a free-text line is allowed.</p>
          )}
          {data.searchOrder.map((channel) => (
            <section key={channel} aria-label={CHANNEL_TITLE[channel] ?? channel}>
              <h3 className={`mb-1 text-xs font-semibold uppercase tracking-wide ${data.recommendedChannel === channel ? 'text-[#1A56DB]' : 'text-slate-500'}`}>
                {CHANNEL_TITLE[channel] ?? label(channel)}{data.recommendedChannel === channel ? ' · recommended' : ''}
              </h3>
              <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">{groupBody(channel)}</div>
            </section>
          ))}
        </div>
      )}
    </Card>
  );
}

function Hit({ title, meta, action }: { title: string; meta: string; action: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
      <div className="min-w-0"><p className="text-sm font-medium">{title}</p><p className="text-xs text-slate-500">{meta}</p></div>
      <div>{action}</div>
    </div>
  );
}

function NoHits() {
  return <p className="px-3 py-2 text-sm text-slate-500">No matches</p>;
}

function MaterialPicker({ reference, onAdd }: { reference: Reference; onAdd: (number: string) => void }) {
  const [value, setValue] = useState('');
  return (
    <div className="flex items-center gap-2">
      <Select aria-label="Material to add" value={value} onChange={(e) => setValue(e.target.value)}
        options={[{ value: '', label: 'Add a material line…' }, ...reference.materials.map((m) => ({ value: m.number, label: `${m.number} · ${m.description}` }))]} />
      <Button type="button" disabled={!value} onClick={() => { onAdd(value); setValue(''); }}>Add</Button>
    </div>
  );
}

// ---------------------------------------------------------------- line editor
function LineEditor({ lineNo, line, reference, onChange, onRemove }: {
  lineNo: number; line: DraftLine; reference: Reference;
  onChange: (patch: Partial<DraftLine>) => void; onRemove: () => void;
}) {
  const free = line.item_type === 'FREE_TEXT';
  const needsAccount = NEEDS_ACCOUNT.includes(line.purchase_type);
  const typeOptions = line.item_type === 'MATERIAL' ? ['STOCK', ...PURCHASE_TYPES] : PURCHASE_TYPES;
  const value = (Number(line.qty) || 0) * (Number(line.price) || 0);
  return (
    <fieldset className="rounded-lg border border-slate-200 p-4">
      <legend className="sr-only">Line {lineNo}</legend>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-slate-500">{lineNo}</span>
          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">{label(line.item_type)}</span>
          <span className="text-sm font-medium">{free ? (line.description || 'Free-text item') : `${line.material ? `${line.material} · ` : ''}${line.description}`}</span>
          <span className="text-xs text-slate-500">from {line.source}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm tabular-nums text-slate-700">{inr(Math.round(value * 100))}</span>
          <Button type="button" variant="ghost" onClick={onRemove} aria-label={`Remove line ${lineNo}`}>Remove</Button>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        {free && (
          <>
            <div className="md:col-span-2"><Field label="Description *">{(id) => <Input id={id} value={line.description} onChange={(e) => onChange({ description: e.target.value })} />}</Field></div>
            <Field label="Material group *">{(id) => <Input id={id} list="pic-material-groups" value={line.material_group} onChange={(e) => onChange({ material_group: e.target.value })} />}</Field>
            <Field label="Category">{(id) => <Input id={id} list="pic-categories" value={line.category} onChange={(e) => onChange({ category: e.target.value })} placeholder="Defaults to material group" />}</Field>
          </>
        )}
        <Field label="Purchase type">{(id) => (
          <Select id={id} value={line.purchase_type} onChange={(e) => onChange({ purchase_type: e.target.value, ...(e.target.value === 'STOCK' ? { aat: '', aac: '' } : {}) })}
            options={typeOptions.map((t) => ({ value: t, label: label(t) }))} />
        )}</Field>
        <Field label="Quantity *">{(id) => <Input id={id} type="number" min="0" step="any" value={line.qty} onChange={(e) => onChange({ qty: e.target.value })} />}</Field>
        <Field label="Unit of measure">{(id) => <Input id={id} value={line.uom} disabled={!free} onChange={(e) => onChange({ uom: e.target.value.toUpperCase() })} />}</Field>
        <Field label={`Estimated unit price (₹)${line.priceFixed ? '' : ' *'}`} hint={line.priceFixed ? 'Catalogue price' : undefined}>{(id) => (
          <Input id={id} type="number" min="0" step="0.01" value={line.price} disabled={line.priceFixed} onChange={(e) => onChange({ price: e.target.value })} />
        )}</Field>
        <Field label="Need date *">{(id) => <Input id={id} type="date" value={line.need_date} onChange={(e) => onChange({ need_date: e.target.value })} />}</Field>
        {(needsAccount || line.aat) && (
          <AccountAssignment type={line.aat} code={line.aac} costObjects={reference.costObjects} required={needsAccount}
            onChange={(aat, aac) => onChange({ aat, aac })} />
        )}
        {free && (
          <>
            <Field label="Quotes attached" hint="Free text above the quote threshold needs 1 or 3 quotes (checked on submit)">{(id) => (
              <Input id={id} type="number" min="0" step="1" value={line.quotes} onChange={(e) => onChange({ quotes: e.target.value })} />
            )}</Field>
            <div className="flex flex-col justify-end gap-2 md:col-span-2">
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-0.5" checked={line.reusable} onChange={(e) => onChange({ reusable: e.target.checked })} />
                <span>Reusable item — start a material master request in parallel (MDM). The requisition does not wait for it.</span>
              </label>
              {line.reusable && (
                <Field label="Manufacturer part number (optional)">{(id) => <Input id={id} value={line.mpn} onChange={(e) => onChange({ mpn: e.target.value })} />}</Field>
              )}
            </div>
          </>
        )}
      </div>
      {line.item_type !== 'FREE_TEXT' && line.qty && <p className="mt-2 text-xs text-slate-500">{fmtQty(line.qty, line.uom)} at {line.price ? inr(rupeesToMinor(line.price)) : '–'}</p>}
    </fieldset>
  );
}

