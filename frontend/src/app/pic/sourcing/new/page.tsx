'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { Button, Card, Empty, Field, Input, Loading, PageHeader, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { inr, label, qty, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand, useList } from '@/lib/pic/hooks';

type Requisition = { id: string; number: string; status: string; purpose_text: string | null; plant: string; total_minor: number };
type PrLine = { line_no: number; description: string; qty: string; uom: string; plant: string; category: string | null;
  material_group: string | null; sourcing_status: string | null; price_est_minor: number | null };
type RequisitionDetail = Requisition & { lines: PrLine[] };
type Supplier = { id: string; code: string; legal_name: string; status: string; categories: Record<string, string> };
type CreatedEvent = { number: string };

type Source = { requisition: string; line: number; qty: string };
type LineSel = { key: string; requisition: string; line: number; description: string; uom: string; annual_qty: string; monthly_qty: string;
  lot: string; baseline: string; sources?: Source[] };
type CriterionRow = { code: string; name: string; weight: string; data_source: string };
type Candidate = { code: string; name: string; status: string; waiverNeeded: boolean; segment: string; riskScore: number; riskLevel: string; openSignals: string[] };
type CandidateResult = { candidates: Candidate[]; hiddenByFilter: { segment: number; risk: number; signals: number } };
type BundleItem = { requisition: string; line: number; origin: string; category: string; description: string; plant: string; qty: string; uom: string;
  needDate: string; valueMinor: number };
type BundleResult = { items: BundleItem[]; totalValueMinor: number };
type BundlePreview = { lines: { description: string; qty: string; annual_qty: string; monthly_qty: string; uom: string; sources: Source[]; valueMinor: number }[];
  warnings: string[]; category: string | null; estimatedValueMinor: number };
type CategoryPlan = { number: string; category: string; fiscal_year: string };

const TYPES = [
  { value: 'RFQ', label: 'RFQ – request for quotation' },
  { value: 'RFP', label: 'RFP – request for proposal' },
  { value: 'RFI', label: 'RFI – request for information' },
  { value: 'REVERSE_AUCTION', label: 'Reverse auction' },
];
const CRITERIA_CODES: Record<string, string> = {
  PRICE_TCO: 'Price / TCO', QUALITY: 'Quality', DELIVERY: 'Delivery', TECHNICAL: 'Technical', ESG: 'ESG', RISK: 'Risk', RESPONSIVENESS: 'Responsiveness',
};
const SEGMENTS = ['STRATEGIC', 'LEVERAGE', 'BOTTLENECK', 'ROUTINE', 'UNSEGMENTED'];
const DEFAULT_CRITERIA: CriterionRow[] = [
  { code: 'PRICE_TCO', name: 'Price / TCO', weight: '50', data_source: 'MANUAL' },
  { code: 'QUALITY', name: 'Quality', weight: '20', data_source: 'MANUAL' },
  { code: 'DELIVERY', name: 'Delivery', weight: '15', data_source: 'MANUAL' },
  { code: 'TECHNICAL', name: 'Technical', weight: '10', data_source: 'MANUAL' },
  { code: 'ESG', name: 'ESG', weight: '5', data_source: 'MANUAL' },
];
// Criteria whose score can come from platform data at close instead of an evaluator: code -> data source.
const DATA_SOURCE_FOR: Record<string, { value: string; label: string }> = {
  QUALITY: { value: 'SCORECARD', label: 'Supplier scorecard (PPM)' },
  DELIVERY: { value: 'SCORECARD', label: 'Supplier scorecard (OTIF)' },
  RESPONSIVENESS: { value: 'SCORECARD', label: 'Supplier scorecard (RFQ response)' },
  ESG: { value: 'ESG', label: 'Accepted ESG assessment' },
  RISK: { value: 'RISK', label: 'Open risk signals' },
};
const BASELINE_METHODS = [
  { value: 'LAST_PRICE', label: 'Last price paid (info record)' },
  { value: 'STANDARD_PRICE', label: 'Standard price' },
  { value: 'SHOULD_COST', label: 'Should-cost model' },
  { value: 'BUDGET', label: 'Budget price' },
];
const ELIGIBLE = ['QUALIFIED', 'PREFERRED'];
const SHOULD_COST_FIELDS: { key: string; label: string; hint?: string; required: boolean }[] = [
  { key: 'net_weight_kg', label: 'Net weight (kg)', required: true },
  { key: 'alloy_rate_per_kg', label: 'Alloy rate (₹/kg)', required: true },
  { key: 'cycle_time_min', label: 'Cycle time (min)', required: true },
  { key: 'machine_rate_per_min', label: 'Machine rate (₹/min)', required: true },
  { key: 'tooling_amortisation', label: 'Tooling amortisation (₹/unit)', required: false },
  { key: 'packaging', label: 'Packaging (₹/unit)', required: false },
  { key: 'overhead_margin_pct', label: 'Overhead + margin (%)', required: true },
];

function toLocalInput(d: Date) {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

const num = (v: string) => (v.trim() === '' ? NaN : Number(v));

export default function NewSourcingEvent() {
  const router = useRouter();
  const [type, setType] = useState('RFQ');
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState('');
  const [lines, setLines] = useState<LineSel[]>([]);
  const [criteria, setCriteria] = useState<CriterionRow[]>(DEFAULT_CRITERIA);
  const [invitees, setInvitees] = useState<Record<string, { selected: boolean; waiver: string }>>({});
  const [closeAt, setCloseAt] = useState(() => toLocalInput(new Date(Date.now() + 7 * 864e5)));
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);
  const [baselineMethod, setBaselineMethod] = useState('LAST_PRICE');
  const [baselinePrice, setBaselinePrice] = useState('');
  const [useShouldCost, setUseShouldCost] = useState(false);
  const [shouldCost, setShouldCost] = useState<Record<string, string>>({});
  const [maxSuppliers, setMaxSuppliers] = useState('2');
  const [maxShare, setMaxShare] = useState('60');
  const [minShare, setMinShare] = useState('20');
  const [maxRisk, setMaxRisk] = useState('');
  const [maxSingle, setMaxSingle] = useState('');
  const [maxConditional, setMaxConditional] = useState('');
  const [maxTotal, setMaxTotal] = useState('');
  const [requireAll, setRequireAll] = useState(false);
  const [bundle, setBundle] = useState<{ kind: string; ref: string }>({ kind: 'PR_LINES', ref: '' });
  const [segmentFilter, setSegmentFilter] = useState('');
  const [riskFilter, setRiskFilter] = useState('');
  const [savingsTarget, setSavingsTarget] = useState('');
  const [attempted, setAttempted] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const suppliers = useList<Supplier>('/suppliers');
  const categoryOptions = useMemo(() => Array.from(new Set(suppliers.items.flatMap((s) => Object.keys(s.categories ?? {})))).sort(), [suppliers.items]);

  const weightTotal = criteria.reduce((sum, c) => sum + (Number(c.weight) || 0), 0);
  const duplicateCodes = criteria.map((c) => c.code).filter((c, i, all) => all.indexOf(c) !== i);
  const candidateQuery = category
    ? `/sourcing/invitee-candidates?category=${encodeURIComponent(category)}${segmentFilter ? `&segment=${segmentFilter}` : ''}${riskFilter ? `&maxRisk=${riskFilter}` : ''}`
    : null;
  const candidates = useApi<CandidateResult>(candidateQuery);
  const chosen = suppliers.items.filter((s) => invitees[s.code]?.selected);
  const lotCounts = lines.reduce<Record<string, number>>((acc, l) => (l.lot.trim() ? { ...acc, [l.lot.trim().toUpperCase()]: (acc[l.lot.trim().toUpperCase()] ?? 0) + 1 } : acc), {});
  const closeDate = new Date(closeAt);

  const problems: string[] = [];
  if (!title.trim()) problems.push('Give the event a title.');
  if (!category.trim()) problems.push('Choose the category being sourced.');
  if (!lines.length) problems.push('Add at least one requirement line from an approved requisition.');
  if (lines.length > 1 && type === 'REVERSE_AUCTION') problems.push('A live reverse auction ranks one price ladder: use one line, or an RFQ / RFP for several lines.');
  Object.entries(lotCounts).filter(([, n]) => n === 1).forEach(([code]) => problems.push(`Lot ${code} has a single line; a lot groups at least two lines.`));
  lines.forEach((l) => {
    if (!(num(l.annual_qty) > 0) || !(num(l.monthly_qty) > 0)) problems.push(`${l.requisition}/${l.line}: annual and monthly quantity must be positive.`);
  });
  if (!criteria.length) problems.push('Add scoring criteria.');
  if (weightTotal !== 100) problems.push(`Scoring weights must total 100 (currently ${weightTotal}).`);
  if (duplicateCodes.length) problems.push(`Each criterion code can be used once (${Array.from(new Set(duplicateCodes)).join(', ')}).`);
  if (criteria.some((c) => !c.name.trim())) problems.push('Every criterion needs a name.');
  if (!chosen.length) problems.push('Invite at least one qualified supplier.');
  chosen.forEach((s) => {
    if (s.categories?.[category] === 'CONDITIONAL' && !invitees[s.code]?.waiver.trim()) problems.push(`${s.code} is Conditional – a waiver reason is required.`);
  });
  if (Number.isNaN(closeDate.getTime()) || closeDate.getTime() <= now) problems.push('Close date-time must be in the future.');
  if (baselinePrice && !(Number(baselinePrice) > 0)) problems.push('Baseline price must be a positive amount.');
  if (useShouldCost) SHOULD_COST_FIELDS.filter((f) => f.required).forEach((f) => {
    if (!(num(shouldCost[f.key] ?? '') >= 0)) problems.push(`Should-cost: ${f.label} is required.`);
  });
  const opt = (v: string, low: number, high: number, name: string) => {
    if (v.trim() !== '' && !(Number(v) >= low && Number(v) <= high)) problems.push(`${name} must be between ${low} and ${high}.`);
  };
  opt(maxRisk, 0, 100, 'Maximum risk score'); opt(maxSingle, 1, 100, 'Single-source cap (%)'); opt(maxConditional, 0, 100, 'Conditional-supplier cap (%)');
  opt(maxTotal, 1, 50, 'Maximum suppliers across the event');
  const maxS = Number(maxShare), minS = Number(minShare), maxN = Number(maxSuppliers);
  if (!(maxN >= 1) || !Number.isInteger(maxN)) problems.push('Max suppliers must be a whole number ≥ 1.');
  if (!(maxS > 0 && maxS <= 100) || !(minS >= 0 && minS <= 100) || minS > maxS) problems.push('Shares must be 0–100 % with min share ≤ max share.');

  const shouldCostPreview = useMemo(() => {
    if (!useShouldCost) return null;
    const v = (k: string) => Number(shouldCost[k] || 0);
    const material = v('net_weight_kg') * v('alloy_rate_per_kg');
    const conversion = v('cycle_time_min') * v('machine_rate_per_min');
    const subtotal = material + conversion + v('tooling_amortisation') + v('packaging');
    return { material, conversion, subtotal, unit: subtotal * (1 + v('overhead_margin_pct') / 100) };
  }, [useShouldCost, shouldCost]);

  const body = () => ({
    type, title: title.trim(), category: category.trim(),
    lines: lines.map((l) => ({
      ...(l.sources ? { sources: l.sources.map((s) => ({ requisition: s.requisition, line: s.line, qty: s.qty })) } : { requisition: l.requisition, line: l.line }),
      annual_qty: l.annual_qty, monthly_qty: l.monthly_qty, lot: l.lot.trim() ? l.lot.trim().toUpperCase() : undefined,
      baseline_price_minor: l.baseline ? rupeesToMinor(l.baseline) : undefined,
    })),
    criteria: criteria.map((c) => ({ code: c.code, name: c.name.trim(), weight: Number(c.weight), data_source: c.data_source === 'MANUAL' ? undefined : c.data_source })),
    invitees: chosen.map((s) => ({ supplier: s.code, waiver_reason: invitees[s.code]?.waiver.trim() || undefined })),
    close_at: closeDate.toISOString(),
    baseline_method: baselineMethod,
    baseline_price_minor: baselinePrice ? rupeesToMinor(baselinePrice) : undefined,
    should_cost_params: useShouldCost
      ? Object.fromEntries(SHOULD_COST_FIELDS.filter((f) => (shouldCost[f.key] ?? '') !== '').map((f) => [f.key, shouldCost[f.key]]))
      : undefined,
    constraints: {
      max_suppliers: maxN, max_share: (maxS / 100).toFixed(2), min_share: (minS / 100).toFixed(2),
      ...(maxRisk.trim() ? { max_risk_score: Number(maxRisk) } : {}), ...(maxSingle.trim() ? { max_single_source_pct: Number(maxSingle) } : {}),
      ...(maxConditional.trim() ? { max_conditional_share_pct: Number(maxConditional) } : {}), ...(maxTotal.trim() ? { max_total_suppliers: Number(maxTotal) } : {}),
      ...(requireAll ? { require_all_lines: true } : {}),
    },
    savings_target_pct: savingsTarget || undefined,
    bundle: lines.length > 1 || lines.some((l) => l.sources) ? { kind: bundle.kind, ref: bundle.kind === 'CATEGORY_PLAN' ? bundle.ref || undefined : undefined } : undefined,
  });

  const create = useCommand(async (publish: boolean) => {
    setError(null);
    const event = await api.post<CreatedEvent>('/sourcing/events', body());
    if (publish) {
      try {
        await api.post(`/sourcing/events/${encodeURIComponent(event.number)}/publish`);
      } catch (e) {
        // The draft exists; open it so the problem can be fixed there.
        router.push(`/pic/sourcing/${encodeURIComponent(event.number)}`);
        throw e;
      }
    }
    return { ...event, published: publish };
  }, {
    success: (r) => (r.published ? `${r.number} published – bids are sealed until close` : `${r.number} saved as draft`),
    onSuccess: (r) => router.push(`/pic/sourcing/${encodeURIComponent(r.number)}`),
  });

  const submit = (publish: boolean) => {
    setAttempted(true);
    if (problems.length) return;
    create.mutate(publish, { onError: (e) => setError(e) });
  };

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="SRC-02 · Event builder" title="New sourcing event"
        subtitle="Build the event from approved requirements, lock a scoring model that totals 100, and invite only suppliers qualified for the category (P06)." />

      <Card title="1 · Event">
        <div className="grid gap-4 md:grid-cols-3">
          <Field label="Event type">{(id) => <Select id={id} value={type} onChange={(e) => setType(e.target.value)} options={TYPES} />}</Field>
          <Field label="Title">{(id) => <Input id={id} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. DC-330 housing – annual requirement" required />}</Field>
          <Field label="Category" hint="Supplier eligibility is checked against this category.">{(id) => (
            <>
              <Input id={id} list="src-categories" value={category} onChange={(e) => setCategory(e.target.value.toUpperCase())} placeholder="e.g. ALU-DIECAST" required />
              <datalist id="src-categories">{categoryOptions.map((c) => <option key={c} value={c} />)}</datalist>
            </>
          )}</Field>
          <Field label="Close date-time" hint={type === 'REVERSE_AUCTION' ? 'The live auction ends at this moment; late bids extend it (soft close). One line per auction.' : 'Bids stay sealed until this moment.'}>{(id) => <Input id={id} type="datetime-local" value={closeAt} onChange={(e) => setCloseAt(e.target.value)} required />}</Field>
          <Field label="Savings target (%)" hint="Optional">{(id) => <Input id={id} type="number" min="0" step="0.1" value={savingsTarget} onChange={(e) => setSavingsTarget(e.target.value)} />}</Field>
        </div>
      </Card>

      <Card title="2 · Requirement lines (approved requisitions; several items and lots per event)">
        <BundleBuilder category={category} bundle={bundle} onBundle={setBundle} onApply={(proposal) => {
          if (proposal.category && !category) setCategory(proposal.category);
          setLines(proposal.lines.map((l, i) => ({
            key: `bundle-${i}-${l.sources[0].requisition}-${l.sources[0].line}`, requisition: l.sources[0].requisition, line: l.sources[0].line, description: l.description,
            uom: l.uom, annual_qty: l.annual_qty, monthly_qty: l.monthly_qty, lot: '', baseline: '', sources: l.sources,
          })));
        }} />
        <div className="mt-4"><RequirementPicker lines={lines} onAdd={(l) => setLines((prev) => [...prev, l])} /></div>
        {lines.length > 0 && (
          <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr><th className="px-3 py-2">Requirement</th><th className="px-3 py-2">Item</th><th className="px-3 py-2">Annual qty</th><th className="px-3 py-2">Monthly qty</th>
                  <th className="px-3 py-2">Lot</th><th className="px-3 py-2">Baseline ₹/unit</th><th className="px-3 py-2"><span className="sr-only">Remove</span></th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {lines.map((l, i) => (
                  <tr key={l.key}>
                    <td className="px-3 py-2 font-mono text-xs">{l.sources ? l.sources.map((s) => `${s.requisition}/${s.line}`).join(', ') : `${l.requisition} / ${l.line}`}</td>
                    <td className="px-3 py-2">{l.description} <span className="text-xs text-slate-500">({l.uom})</span></td>
                    <td className="px-3 py-2"><Input aria-label={`Annual quantity for ${l.requisition} line ${l.line}`} type="number" min="0" value={l.annual_qty}
                      onChange={(e) => setLines((p) => p.map((x, j) => (j === i ? { ...x, annual_qty: e.target.value } : x)))} className="w-32" /></td>
                    <td className="px-3 py-2"><Input aria-label={`Monthly quantity for ${l.requisition} line ${l.line}`} type="number" min="0" value={l.monthly_qty}
                      onChange={(e) => setLines((p) => p.map((x, j) => (j === i ? { ...x, monthly_qty: e.target.value } : x)))} className="w-32" /></td>
                    <td className="px-3 py-2"><Input aria-label={`Lot for line ${i + 1}`} value={l.lot} placeholder="none" maxLength={20} className="w-24"
                      onChange={(e) => setLines((p) => p.map((x, j) => (j === i ? { ...x, lot: e.target.value.toUpperCase() } : x)))} /></td>
                    <td className="px-3 py-2"><Input aria-label={`Baseline price for line ${i + 1}`} type="number" min="0" step="0.01" value={l.baseline} placeholder="last price" className="w-28"
                      onChange={(e) => setLines((p) => p.map((x, j) => (j === i ? { ...x, baseline: e.target.value } : x)))} /></td>
                    <td className="px-3 py-2 text-right"><Button variant="ghost" onClick={() => setLines((p) => p.filter((_, j) => j !== i))}>Remove</Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-xs text-slate-500">Each line is bid, evaluated and awarded on its own; lines with the same lot code can also be bid as a bundle (discount for the whole lot, optionally all-or-nothing)
          and are then awarded to one supplier as a whole. The monthly quantity is the demand used for the capacity check of that line. With several lines the baseline is the annual value.</p>
      </Card>

      <Card title="3 · Scoring model" actions={
        <span role="status" className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${weightTotal === 100 ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-800'}`}>
          Weights total {weightTotal} / 100 {weightTotal === 100 ? '✓' : `(${weightTotal > 100 ? 'over' : 'short'} by ${Math.abs(100 - weightTotal)})`}
        </span>
      }>
        <div className="space-y-2">
          {criteria.map((c, i) => (
            <div key={i} className="grid grid-cols-[1fr_1.5fr_6rem_auto] items-end gap-2">
              <Field label={i === 0 ? 'Code' : ' '}>{(id) => (
                <Select id={id} aria-label={`Criterion ${i + 1} code`} value={c.code}
                  onChange={(e) => setCriteria((p) => p.map((x, j) => (j === i ? { ...x, code: e.target.value, data_source: 'MANUAL', name: x.name === CRITERIA_CODES[x.code] || !x.name ? CRITERIA_CODES[e.target.value] : x.name } : x)))}
                  options={Object.entries(CRITERIA_CODES).map(([value, name]) => ({ value, label: `${value} – ${name}` }))} />
              )}</Field>
              <Field label={i === 0 ? 'Name' : ' '}>{(id) => <Input id={id} aria-label={`Criterion ${i + 1} name`} value={c.name} onChange={(e) => setCriteria((p) => p.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />}</Field>
              <Field label={i === 0 ? 'Weight' : ' '}>{(id) => <Input id={id} aria-label={`Criterion ${i + 1} weight`} type="number" min="0" max="100" value={c.weight} onChange={(e) => setCriteria((p) => p.map((x, j) => (j === i ? { ...x, weight: e.target.value } : x)))} />}</Field>
              <Button variant="ghost" aria-label={`Remove criterion ${c.code}`} onClick={() => setCriteria((p) => p.filter((_, j) => j !== i))}>Remove</Button>
              {DATA_SOURCE_FOR[c.code] && (
                <label className="col-span-4 flex items-center gap-2 pl-1 text-xs text-slate-600">
                  <input type="checkbox" className="h-3.5 w-3.5" checked={c.data_source !== 'MANUAL'}
                    onChange={(e) => setCriteria((p) => p.map((x, j) => (j === i ? { ...x, data_source: e.target.checked ? DATA_SOURCE_FOR[c.code].value : 'MANUAL' } : x)))} />
                  Score {c.code} from data at close: {DATA_SOURCE_FOR[c.code].label} (no evaluator scoring)
                </label>
              )}
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button onClick={() => {
            const unused = Object.keys(CRITERIA_CODES).find((k) => !criteria.some((c) => c.code === k)) ?? 'RISK';
            setCriteria((p) => [...p, { code: unused, name: CRITERIA_CODES[unused], weight: '0', data_source: 'MANUAL' }]);
          }}>Add criterion</Button>
          <p className="text-xs text-slate-500">PRICE_TCO is scored automatically from total cost of ownership per line. ESG, Risk and the scorecard criteria can take their score from platform data at close
            (frozen on the bid); the others are scored by evaluators after close. Weights lock at publish.</p>
        </div>
      </Card>

      <Card title="4 · Invitees">
        <div className="mb-3 grid gap-3 md:grid-cols-3">
          <Field label="Filter by segment">{(id) => <Select id={id} value={segmentFilter} onChange={(e) => setSegmentFilter(e.target.value)}
            options={[{ value: '', label: 'All segments' }, ...SEGMENTS.map((s) => ({ value: s, label: label(s) }))]} />}</Field>
          <Field label="Filter by risk" hint="Hide suppliers whose risk score is above this.">{(id) => <Select id={id} value={riskFilter} onChange={(e) => setRiskFilter(e.target.value)}
            options={[{ value: '', label: 'Any risk' }, { value: '15', label: 'Low only (score ≤ 15)' }, { value: '40', label: 'Up to medium (score ≤ 40)' }, { value: '70', label: 'Up to high (score ≤ 70)' }]} />}</Field>
          <p className="self-end text-xs text-slate-500">
            {candidates.data ? `${candidates.data.candidates.length} supplier(s) shown; hidden by filter: ${candidates.data.hiddenByFilter.segment} by segment, ${candidates.data.hiddenByFilter.risk} by risk.` : ' '}
          </p>
        </div>
        {candidates.data && candidates.data.candidates.length > 0 && (
          <div className="mb-3 overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-full text-sm">
              <caption className="sr-only">Suppliers eligible for the category with segment and risk</caption>
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-3 py-2">Supplier</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Segment</th><th className="px-3 py-2">Risk</th><th className="px-3 py-2">Open signals</th></tr></thead>
              <tbody className="divide-y divide-slate-100">{candidates.data.candidates.map((c) => (
                <tr key={c.code}><td className="px-3 py-2">{c.name} <span className="font-mono text-xs text-slate-500">{c.code}</span></td><td className="px-3 py-2"><StatusChip status={c.status} /></td>
                  <td className="px-3 py-2">{label(c.segment)}</td><td className="px-3 py-2">{c.riskScore} <span className="text-xs text-slate-500">{label(c.riskLevel)}</span></td>
                  <td className="px-3 py-2 text-xs">{c.openSignals.length ? c.openSignals.map(label).join(', ') : '–'}</td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
        {suppliers.isLoading ? <Loading /> : suppliers.error ? <ProblemBox error={suppliers.error} /> : !category ? (
          <Empty title="Choose a category first" hint="Each supplier's qualification status is shown for the chosen category." />
        ) : (
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
            {suppliers.items.filter((s) => !candidates.data || (!segmentFilter && !riskFilter) || candidates.data.candidates.some((c) => c.code === s.code)).map((s) => {
              const st = s.categories?.[category] ?? 'NOT_REGISTERED';
              const eligible = ELIGIBLE.includes(st) || st === 'CONDITIONAL';
              const sel = invitees[s.code];
              const id = `inv-${s.code}`;
              return (
                <li key={s.code} className={`px-4 py-3 ${eligible ? '' : 'bg-slate-50'}`}>
                  <div className="flex flex-wrap items-center gap-3">
                    <input id={id} type="checkbox" className="h-4 w-4" disabled={!eligible} checked={!!sel?.selected}
                      onChange={(e) => setInvitees((p) => ({ ...p, [s.code]: { selected: e.target.checked, waiver: p[s.code]?.waiver ?? '' } }))} />
                    <label htmlFor={id} className={`text-sm ${eligible ? 'font-medium' : 'text-slate-500'}`}>{s.legal_name} <span className="font-mono text-xs text-slate-500">{s.code}</span></label>
                    <StatusChip status={st} />
                    {!eligible && <span className="text-xs text-slate-500">Not selectable – only Qualified/Preferred (or Conditional with waiver) suppliers may be invited.</span>}
                  </div>
                  {st === 'CONDITIONAL' && sel?.selected && (
                    <div className="mt-2 pl-7">
                      <Field label="Waiver reason (required for a Conditional supplier)">{(fid) => (
                        <Textarea id={fid} value={sel.waiver} onChange={(e) => setInvitees((p) => ({ ...p, [s.code]: { selected: true, waiver: e.target.value } }))} />
                      )}</Field>
                    </div>
                  )}
                </li>
              );
            })}
            {suppliers.hasNextPage && <li className="px-4 py-2 text-center"><Button busy={suppliers.isFetchingNextPage} onClick={() => suppliers.fetchNextPage()}>Load more suppliers</Button></li>}
          </ul>
        )}
      </Card>

      <Card title="5 · Baseline, should-cost and award constraints">
        <div className="grid gap-4 md:grid-cols-3">
          <Field label="Baseline method">{(id) => <Select id={id} value={baselineMethod} onChange={(e) => setBaselineMethod(e.target.value)} options={BASELINE_METHODS} />}</Field>
          <Field label="Baseline price per unit (₹)" hint="Optional – with ‘last price paid’ it is read from the info record.">{(id) => <Input id={id} type="number" min="0" step="0.01" value={baselinePrice} onChange={(e) => setBaselinePrice(e.target.value)} />}</Field>
          <div className="flex items-end">
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4" checked={useShouldCost} onChange={(e) => setUseShouldCost(e.target.checked)} /> Add a parametric should-cost model</label>
          </div>
        </div>
        {useShouldCost && (
          <div className="mt-4 rounded-lg bg-slate-50 p-4">
            <div className="grid gap-3 md:grid-cols-4">
              {SHOULD_COST_FIELDS.map((f) => (
                <Field key={f.key} label={`${f.label}${f.required ? '' : ' (optional)'}`}>{(id) => (
                  <Input id={id} type="number" min="0" step="any" value={shouldCost[f.key] ?? ''} onChange={(e) => setShouldCost((p) => ({ ...p, [f.key]: e.target.value }))} />
                )}</Field>
              ))}
            </div>
            {shouldCostPreview && (
              <p className="mt-3 text-sm text-slate-700">
                Material ₹{shouldCostPreview.material.toFixed(2)} + conversion ₹{shouldCostPreview.conversion.toFixed(2)} + tooling + packaging = ₹{shouldCostPreview.subtotal.toFixed(2)};
                with overhead/margin the <span className="font-semibold">should-cost is ₹{shouldCostPreview.unit.toFixed(2)} / unit</span>.
              </p>
            )}
          </div>
        )}
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <Field label="Max suppliers awarded">{(id) => <Input id={id} type="number" min="1" step="1" value={maxSuppliers} onChange={(e) => setMaxSuppliers(e.target.value)} />}</Field>
          <Field label="Max share per supplier (%)">{(id) => <Input id={id} type="number" min="0" max="100" value={maxShare} onChange={(e) => setMaxShare(e.target.value)} />}</Field>
          <Field label="Min share per awarded supplier (%)">{(id) => <Input id={id} type="number" min="0" max="100" value={minShare} onChange={(e) => setMinShare(e.target.value)} />}</Field>
        </div>
        <p className="mt-2 text-xs text-slate-500">The capacity-constrained award scenario also caps each supplier at its verified free capacity from the digital twin. Shares apply per line; a lot awarded as a bundle is indivisible.</p>
        <div className="mt-4 grid gap-4 md:grid-cols-4">
          <Field label="Risk constraint: max risk score" hint="Suppliers above it are left out of every scenario (blocked ones always are).">{(id) => <Input id={id} type="number" min="0" max="100" value={maxRisk} onChange={(e) => setMaxRisk(e.target.value)} placeholder="no cap" />}</Field>
          <Field label="No single supplier above (% of award value)">{(id) => <Input id={id} type="number" min="1" max="100" value={maxSingle} onChange={(e) => setMaxSingle(e.target.value)} placeholder="no cap" />}</Field>
          <Field label="Conditional suppliers at most (% of value)">{(id) => <Input id={id} type="number" min="0" max="100" value={maxConditional} onChange={(e) => setMaxConditional(e.target.value)} placeholder="no cap" />}</Field>
          <Field label="Suppliers across the whole event (max)">{(id) => <Input id={id} type="number" min="1" max="50" value={maxTotal} onChange={(e) => setMaxTotal(e.target.value)} placeholder="no cap" />}</Field>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4" checked={requireAll} onChange={(e) => setRequireAll(e.target.checked)} /> Every bid must price every line (otherwise suppliers may bid some lines)</label>
      </Card>

      {attempted && problems.length > 0 && (
        <div role="alert" className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p className="font-semibold">Fix these before saving</p>
          <ul className="mt-1 list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      )}
      <ProblemBox error={error} />
      <div className="flex flex-wrap justify-end gap-2">
        <Button onClick={() => router.push('/pic/sourcing')}>Cancel</Button>
        <Button busy={create.isPending} onClick={() => submit(false)}>Save draft</Button>
        <Button variant="primary" busy={create.isPending} onClick={() => submit(true)}>Save and publish</Button>
      </div>
    </div>
  );
}

/** Requirement bundling: pick open lines of several requisitions (or MRP demand, or a category plan's category) and merge them into event lines. */
function BundleBuilder({ category, bundle, onBundle, onApply }: {
  category: string; bundle: { kind: string; ref: string }; onBundle: (b: { kind: string; ref: string }) => void; onApply: (p: BundlePreview) => void;
}) {
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [preview, setPreview] = useState<BundlePreview | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const plans = useApi<CategoryPlan[]>(open && bundle.kind === 'CATEGORY_PLAN' ? '/category-plans' : null);
  const plan = (plans.data ?? []).find((x) => x.number === bundle.ref);
  const origin = bundle.kind === 'MRP_DEMAND' ? 'origin=MRP' : '';
  const scope = bundle.kind === 'CATEGORY_PLAN' ? (plan ? `category_plan=${encodeURIComponent(plan.number)}` : null) : category ? `category=${encodeURIComponent(category)}` : '';
  const candidates = useApi<BundleResult>(open && scope !== null ? `/sourcing/bundle-candidates?${[origin, scope].filter(Boolean).join('&')}` : null);
  const key = (i: BundleItem) => `${i.requisition}/${i.line}`;
  const chosen = (candidates.data?.items ?? []).filter((i) => picked[key(i)]);
  const run = useCommand(async () => api.post<BundlePreview>('/sourcing/bundles/preview', {
    lines: chosen.map((i) => ({ requisition: i.requisition, line: i.line })), kind: bundle.kind, ref: bundle.ref || undefined }), {
    onSuccess: (r) => { setPreview(r); setError(null); },
  });
  if (!open) return <Button onClick={() => setOpen(true)}>Bundle requirements (several requisitions, MRP demand or a category plan)…</Button>;
  return (
    <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Bundle from">{(id) => <Select id={id} value={bundle.kind} onChange={(e) => { onBundle({ kind: e.target.value, ref: '' }); setPicked({}); setPreview(null); }}
          options={[{ value: 'PR_LINES', label: 'Requisition lines' }, { value: 'MRP_DEMAND', label: 'MRP demand (requisitions from MRP runs)' }, { value: 'CATEGORY_PLAN', label: 'Category plan' }]} />}</Field>
        {bundle.kind === 'CATEGORY_PLAN' && (
          <Field label="Category plan">{(id) => <Select id={id} value={bundle.ref} onChange={(e) => { onBundle({ kind: 'CATEGORY_PLAN', ref: e.target.value }); setPicked({}); }}
            options={[{ value: '', label: 'Choose a plan…' }, ...(plans.data ?? []).map((x) => ({ value: x.number, label: `${x.number} · ${x.category} · ${x.fiscal_year}` }))]} />}</Field>
        )}
        <div className="flex items-end gap-2"><Button onClick={() => setOpen(false)}>Close</Button></div>
      </div>
      {candidates.isLoading ? <Loading /> : candidates.error ? <ProblemBox error={candidates.error} /> : candidates.data && (
        candidates.data.items.length === 0 ? <Empty title="No open requirement lines" hint="Only approved requisition lines that are not yet in sourcing can be bundled." /> : (
          <ul className="max-h-64 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200 bg-white">
            {candidates.data.items.map((i) => (
              <li key={key(i)} className="flex items-center gap-3 px-3 py-2 text-sm">
                <input type="checkbox" className="h-4 w-4" aria-label={`Bundle ${key(i)}`} checked={!!picked[key(i)]} onChange={(e) => setPicked((p) => ({ ...p, [key(i)]: e.target.checked }))} />
                <span className="font-mono text-xs text-slate-500">{key(i)}</span><span className="font-medium">{i.description}</span>
                <span className="text-slate-600">· {qty(i.qty, i.uom)} · {i.plant} · {label(i.origin)}</span><span className="ml-auto">{inr(i.valueMinor)}</span>
              </li>
            ))}
          </ul>
        )
      )}
      <ProblemBox error={error} />
      <div className="flex flex-wrap items-center gap-2">
        <Button busy={run.isPending} disabled={!chosen.length} onClick={() => run.mutate(undefined, { onError: (e) => setError(e) })}>Preview merged lines ({chosen.length} selected)</Button>
        {preview && <Button variant="primary" disabled={preview.lines.length === 0} onClick={() => { onApply(preview); setOpen(false); }}>Use these {preview.lines.length} line(s)</Button>}
      </div>
      {preview && (
        <div className="text-sm">
          {preview.warnings.length > 0 && <ul className="mb-2 list-disc pl-5 text-amber-800">{preview.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
            {preview.lines.map((l, i) => (
              <li key={i} className="px-3 py-2">{l.description} · {qty(l.qty, l.uom)} <span className="text-xs text-slate-500">from {l.sources.map((s) => `${s.requisition}/${s.line}`).join(', ')}</span></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RequirementPicker({ lines, onAdd }: { lines: LineSel[]; onAdd: (l: LineSel) => void }) {
  const reqs = useList<Requisition>('/requisitions?status=APPROVED');
  const [selected, setSelected] = useState('');
  const detail = useApi<RequisitionDetail>(selected ? `/requisitions/${encodeURIComponent(selected)}` : null);
  if (reqs.isLoading) return <Loading text="Loading approved requisitions…" />;
  if (reqs.error) return <ProblemBox error={reqs.error} />;
  if (!reqs.items.length) return <Empty title="No approved requisitions" hint="Sourcing events can only start from an approved requirement (P06)." />;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[18rem] flex-1">
          <Field label="Approved requisition">{(id) => (
            <Select id={id} value={selected} onChange={(e) => setSelected(e.target.value)}
              options={[{ value: '', label: 'Choose a requisition…' }, ...reqs.items.map((r) => ({ value: r.number, label: `${r.number} · ${r.purpose_text ?? ''} · ${r.plant} · ${inr(r.total_minor)}` }))]} />
          )}</Field>
        </div>
        {reqs.hasNextPage && <Button busy={reqs.isFetchingNextPage} onClick={() => reqs.fetchNextPage()}>Load more</Button>}
      </div>
      {selected && (detail.isLoading ? <Loading /> : detail.error ? <ProblemBox error={detail.error} /> : detail.data && (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
          {detail.data.lines.map((l) => {
            const added = lines.some((x) => x.requisition === selected && x.line === l.line_no);
            const inSourcing = l.sourcing_status && l.sourcing_status !== 'OPEN';
            return (
              <li key={l.line_no} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-sm">
                <div>
                  <span className="font-mono text-xs text-slate-500">Line {l.line_no}</span>{' '}
                  <span className="font-medium">{l.description}</span>{' '}
                  <span className="text-slate-600">· {qty(l.qty, l.uom)} · {l.plant}{l.category ? ` · ${l.category}` : ''}</span>
                  {inSourcing && <span className="ml-2 text-xs text-amber-700">sourcing status: {label(l.sourcing_status)}</span>}
                </div>
                <Button disabled={added || !!inSourcing} title={inSourcing ? 'This requirement line is already in sourcing' : undefined} onClick={() => {
                  const annual = Number(l.qty);
                  onAdd({ key: `${selected}-${l.line_no}`, requisition: selected, line: l.line_no, description: l.description, uom: l.uom,
                    annual_qty: String(annual), monthly_qty: String(Math.max(1, Math.round(annual / 12))), lot: '', baseline: '' });
                }}>{added ? 'Added' : 'Add line'}</Button>
              </li>
            );
          })}
        </ul>
      ))}
    </div>
  );
}
