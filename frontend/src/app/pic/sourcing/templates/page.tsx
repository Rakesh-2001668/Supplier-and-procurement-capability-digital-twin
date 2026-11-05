'use client';

import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, LinkButton, PageHeader, ProblemBox, Select } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { BASELINE_METHODS, MANAGE_ROLES, SCORING_METHODS, useCan } from '../_lib';

type Template = {
  code: string; name: string; eventType: string; category: string | null;
  payload: {
    criteria?: { code: string; name: string; weight: number; data_source?: string; min_score?: string | null }[]; constraints?: Record<string, unknown>; scoring_method?: string;
    baseline_method?: string; invitee_filter?: Record<string, unknown>; auction?: Record<string, unknown>; min_bidders?: number; savings_target_pct?: string; tco_params?: Record<string, unknown>;
  };
};

const TYPES = [{ value: 'RFQ', label: 'RFQ' }, { value: 'RFP', label: 'RFP' }, { value: 'RFI', label: 'RFI' }, { value: 'REVERSE_AUCTION', label: 'Reverse auction' }];
type Crit = { code: string; name: string; weight: string; min_score: string };

function TemplateDialog({ onClose, from }: { onClose: () => void; from?: Template }) {
  const p = from?.payload;
  const [code, setCode] = useState(from?.code ?? '');
  const [name, setName] = useState(from?.name ?? '');
  const [type, setType] = useState(from?.eventType ?? 'RFQ');
  const [category, setCategory] = useState(from?.category ?? '');
  const [criteria, setCriteria] = useState<Crit[]>(p?.criteria?.map((c) => ({ code: c.code, name: c.name, weight: String(c.weight), min_score: c.min_score ? String(c.min_score) : '' }))
    ?? [{ code: 'PRICE_TCO', name: 'Price / TCO', weight: '60', min_score: '' }, { code: 'QUALITY', name: 'Quality', weight: '25', min_score: '' }, { code: 'DELIVERY', name: 'Delivery', weight: '15', min_score: '' }]);
  const [scoring, setScoring] = useState(p?.scoring_method ?? 'LOWEST_RATIO');
  const [baseline, setBaseline] = useState(p?.baseline_method ?? 'LAST_PRICE');
  const [minBidders, setMinBidders] = useState(p?.min_bidders != null ? String(p.min_bidders) : '');
  const [target, setTarget] = useState(p?.savings_target_pct ?? '');
  const [maxSuppliers, setMaxSuppliers] = useState(String(p?.constraints?.max_suppliers ?? '2'));
  const [maxShare, setMaxShare] = useState(p?.constraints?.max_share ? String(Number(p.constraints.max_share) * 100) : '60');
  const [minShare, setMinShare] = useState(p?.constraints?.min_share ? String(Number(p.constraints.min_share) * 100) : '20');
  const [filterMax, setFilterMax] = useState(String(p?.invitee_filter?.max ?? '5'));
  const [filterRisk, setFilterRisk] = useState(p?.invitee_filter?.maxRiskScore != null ? String(p.invitee_filter.maxRiskScore) : '');
  const [error, setError] = useState<ApiError | null>(null);
  const total = criteria.reduce((s, c) => s + (Number(c.weight) || 0), 0);
  const problems: string[] = [];
  if (!/^[A-Za-z0-9_-]{2,40}$/.test(code.trim())) problems.push('Code: 2-40 letters, digits, - or _');
  if (name.trim().length < 2) problems.push('Name');
  if (total !== 100) problems.push(`Weights total ${total}, not 100`);
  if (new Set(criteria.map((c) => c.code.trim().toUpperCase())).size !== criteria.length) problems.push('Criterion codes must be unique');
  const save = useCommand(() => api.post('/sourcing/templates', {
    code: code.trim().toUpperCase(), name: name.trim(), event_type: type, category: category.trim() ? category.trim().toUpperCase() : undefined,
    payload: {
      criteria: criteria.map((c) => ({ code: c.code.trim().toUpperCase(), name: c.name.trim(), weight: Number(c.weight), ...(c.min_score.trim() ? { min_score: c.min_score.trim() } : {}) })),
      scoring_method: scoring, baseline_method: baseline,
      constraints: { max_suppliers: Number(maxSuppliers), max_share: (Number(maxShare) / 100).toFixed(2), min_share: (Number(minShare) / 100).toFixed(2) },
      invitee_filter: { max: Number(filterMax), ...(filterRisk.trim() ? { maxRiskScore: Number(filterRisk) } : {}) },
      ...(minBidders.trim() ? { min_bidders: Number(minBidders) } : {}), ...(target.trim() ? { savings_target_pct: target.trim() } : {}),
    },
  }), { success: 'Template saved', onSuccess: onClose });
  return (
    <Dialog open title={from ? `New version of template ${from.code}` : 'New sourcing template'} onClose={onClose} wide>
      <div className="space-y-4">
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Code" required>{(id) => <Input id={id} value={code} maxLength={40} onChange={(e) => setCode(e.target.value.toUpperCase())} readOnly={!!from} />}</Field>
          <Field label="Name" required>{(id) => <Input id={id} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />}</Field>
          <Field label="Event type">{(id) => <Select id={id} value={type} onChange={(e) => setType(e.target.value)} options={TYPES} />}</Field>
          <Field label="Category" hint="Empty: any category">{(id) => <Input id={id} value={category} onChange={(e) => setCategory(e.target.value.toUpperCase())} />}</Field>
          <Field label="Price scoring method">{(id) => <Select id={id} value={scoring} onChange={(e) => setScoring(e.target.value)} options={SCORING_METHODS} />}</Field>
          <Field label="Baseline method">{(id) => <Select id={id} value={baseline} onChange={(e) => setBaseline(e.target.value)} options={BASELINE_METHODS} />}</Field>
          <Field label="Minimum bidders" hint="Empty: policy value">{(id) => <Input id={id} type="number" min="1" max="20" value={minBidders} onChange={(e) => setMinBidders(e.target.value)} />}</Field>
          <Field label="Savings target (%)">{(id) => <Input id={id} type="number" min="0" max="100" step="0.1" value={target} onChange={(e) => setTarget(e.target.value)} />}</Field>
        </div>
        <fieldset className="space-y-2">
          <legend className="text-sm font-semibold">Criteria <span role="status" className={`ml-2 rounded-full px-2 py-0.5 text-xs ${total === 100 ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-800'}`}>total {total} / 100</span></legend>
          {criteria.map((c, i) => (
            <div key={i} className="grid grid-cols-2 items-end gap-2 md:grid-cols-[1fr_1.5fr_6rem_8rem_auto]">
              <Field label={i === 0 ? 'Code' : ' '}>{(id) => <Input id={id} aria-label={`Criterion ${i + 1} code`} value={c.code} onChange={(e) => setCriteria((p2) => p2.map((x, j) => (j === i ? { ...x, code: e.target.value.toUpperCase() } : x)))} />}</Field>
              <Field label={i === 0 ? 'Name' : ' '}>{(id) => <Input id={id} aria-label={`Criterion ${i + 1} name`} value={c.name} onChange={(e) => setCriteria((p2) => p2.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />}</Field>
              <Field label={i === 0 ? 'Weight' : ' '}>{(id) => <Input id={id} aria-label={`Criterion ${i + 1} weight`} type="number" min="0" max="100" value={c.weight} onChange={(e) => setCriteria((p2) => p2.map((x, j) => (j === i ? { ...x, weight: e.target.value } : x)))} />}</Field>
              <Field label={i === 0 ? 'Gate (min score)' : ' '}>{(id) => <Input id={id} aria-label={`Criterion ${i + 1} minimum score`} type="number" min="0" max="100" value={c.min_score} onChange={(e) => setCriteria((p2) => p2.map((x, j) => (j === i ? { ...x, min_score: e.target.value } : x)))} />}</Field>
              <Button variant="ghost" aria-label={`Remove criterion ${c.code}`} onClick={() => setCriteria((p2) => p2.filter((_, j) => j !== i))}>Remove</Button>
            </div>
          ))}
          <Button onClick={() => setCriteria((p2) => [...p2, { code: '', name: '', weight: '0', min_score: '' }])}>Add criterion</Button>
        </fieldset>
        <div className="grid gap-3 md:grid-cols-5">
          <Field label="Max suppliers awarded">{(id) => <Input id={id} type="number" min="1" max="10" value={maxSuppliers} onChange={(e) => setMaxSuppliers(e.target.value)} />}</Field>
          <Field label="Max share (%)">{(id) => <Input id={id} type="number" min="1" max="100" value={maxShare} onChange={(e) => setMaxShare(e.target.value)} />}</Field>
          <Field label="Min share (%)">{(id) => <Input id={id} type="number" min="0" max="100" value={minShare} onChange={(e) => setMinShare(e.target.value)} />}</Field>
          <Field label="Invite at most" hint="Invitation filter: qualified, lowest risk first">{(id) => <Input id={id} type="number" min="1" max="30" value={filterMax} onChange={(e) => setFilterMax(e.target.value)} />}</Field>
          <Field label="Invite risk score up to">{(id) => <Input id={id} type="number" min="0" max="100" value={filterRisk} onChange={(e) => setFilterRisk(e.target.value)} />}</Field>
        </div>
        {problems.length > 0 && <p className="text-xs text-slate-500">Needed: {problems.join('; ')}.</p>}
        <ProblemBox error={error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={problems.length > 0} busy={save.isPending} onClick={() => save.mutate(undefined, { onError: (e) => setError(e) })}>Save template</Button>
        </div>
      </div>
    </Dialog>
  );
}

export default function TemplatesPage() {
  const can = useCan();
  const canManage = can(MANAGE_ROLES);
  const { data, isLoading, error } = useApi<Template[]>('/sourcing/templates');
  const [dialog, setDialog] = useState<{ from?: Template } | null>(null);
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="SRC-02 · Templates" title="Sourcing templates"
        subtitle="A template keeps what stays the same from one event to the next of a kind: event type, scoring criteria and weights, award constraints, scoring and baseline method and the filter that picks the invitees. An event is then created with the requirement lines and the dates of the day."
        actions={<>
          <LinkButton href="/pic/sourcing">Back to sourcing</LinkButton>
          {canManage && <Button variant="primary" onClick={() => setDialog({})}>New template</Button>}
        </>} />
      <Card>
        <DataTable<Template & Record<string, unknown>>
          caption="Sourcing templates" rows={(data ?? []).map((t) => ({ ...t, id: t.code }))} loading={isLoading} error={error} empty="No templates yet"
          columns={[
            { key: 'code', header: 'Code', render: (t) => <span className="font-mono text-xs font-semibold">{t.code}</span> },
            { key: 'name', header: 'Name' },
            { key: 'eventType', header: 'Type', render: (t) => label(t.eventType) },
            { key: 'category', header: 'Category', render: (t) => t.category ?? 'any' },
            { key: 'criteria', header: 'Criteria', render: (t) => (t.payload.criteria ?? []).map((c) => `${c.code} ${c.weight}%${c.min_score ? ` (gate ${c.min_score})` : ''}`).join(' · ') || '–' },
            { key: 'scoring', header: 'Scoring / baseline', render: (t) => `${label(t.payload.scoring_method ?? 'LOWEST_RATIO')} / ${label(t.payload.baseline_method ?? 'LAST_PRICE')}` },
            { key: 'invite', header: 'Invitees', render: (t) => (t.payload.invitee_filter ? `filter: up to ${String(t.payload.invitee_filter.max ?? 5)}${t.payload.invitee_filter.maxRiskScore != null ? `, risk ≤ ${String(t.payload.invitee_filter.maxRiskScore)}` : ''}` : 'named at creation') },
            { key: 'use', header: '', render: (t) => canManage ? (
              <div className="flex flex-wrap gap-2">
                <LinkButton variant="primary" href={`/pic/sourcing/new?template=${encodeURIComponent(t.code)}`}>Create event</LinkButton>
                <Button onClick={() => setDialog({ from: t })}>New version</Button>
              </div>
            ) : null },
          ]} />
      </Card>
      {dialog && <TemplateDialog from={dialog.from} onClose={() => setDialog(null)} />}
    </div>
  );
}
