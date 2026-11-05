'use client';

import Link from 'next/link';
import { useState } from 'react';
import { TaskPanel } from '@/components/pic/object';
import { Button, Dialog, Facts, Field, Input, Loading, ProblemBox, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { crore, date, dateTime, inr, label, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { useMe } from '../../mrp/_components';

export type Wave = { name: string; start: string; end: string; lever?: string; milestone?: string };
export type PlanRow = {
  id: string; number: string; category: string; fiscal_year: string; spend_minor: number; profit_impact: string; supply_risk: string; kraljic: string;
  evidence: Record<string, unknown>; levers: string[]; waves: string[]; budget_minor: number | null; savings_target_minor: number | null; status: string; owner_id: string;
  approved_by: string | null; approved_at: string | null; version: number; supersedes_id: string | null; submitted_by: string | null; submitted_at: string | null;
  decision_comment: string | null; addressable_minor: number | null; wave_plan: Wave[]; savings_by_lever: Record<string, number>; created_at: string;
};
type PlanDetail = PlanRow & { validation: string[]; leverCatalogue: string[]; versions: { number: string; version: number; status: string }[] };
type Links = { plan: string; category: string; sourcingEvents: { number: string; type: string; title: string; status: string }[]; savingsInitiatives: { number: string; title: string; stage: string }[] };

const EDITORS = ['CATEGORY_MANAGER', 'PROCUREMENT_HEAD', 'CPO'];
const DECIDERS = ['PROCUREMENT_HEAD', 'CPO'];
const minorToRupees = (minor: number | null) => (minor === null || minor === undefined ? '' : String(minor / 100));

/** One category plan: validation, edit, submit, approval chain with the segregation of duties, reject, revise (versions) and the pipeline it feeds. */
export function PlanDialog({ number, onClose }: { number: string; onClose: () => void }) {
  const { roles, me } = useMe();
  const meId = useApi<{ userId: string }>('/me').data?.userId;
  const detail = useApi<PlanDetail>(`/category-plans/${encodeURIComponent(number)}`);
  const links = useApi<Links>(`/category-plans/${encodeURIComponent(number)}/pipeline-links`);
  const [mode, setMode] = useState<'view' | 'edit' | 'reject' | 'revise' | 'approve' | 'submit'>('view');
  const plan = detail.data;
  const isEditor = roles.some((r) => EDITORS.includes(r));
  const isDecider = roles.some((r) => DECIDERS.includes(r));
  const isOwner = !!plan && !!meId && plan.owner_id === meId;
  const isSubmitter = !!plan && !!meId && plan.submitted_by === meId;
  const editable = !!plan && (plan.status === 'DRAFT' || plan.status === 'REJECTED') && isEditor;

  return (
    <Dialog open wide title={`Category plan ${number}`} onClose={onClose}>
      {detail.isLoading ? <Loading /> : detail.error ? <ProblemBox error={detail.error} /> : plan && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <StatusChip status={plan.status} />
            <span className="text-sm text-slate-600">{plan.category} · FY {plan.fiscal_year} · version {plan.version}{isOwner ? ' · you are the owner' : ''}{isSubmitter ? ' · you submitted it' : ''}</span>
          </div>
          <Facts items={[
            ['Position', label(plan.kraljic)], ['Impact / risk', `${Number(plan.profit_impact).toFixed(2)} / ${Number(plan.supply_risk).toFixed(2)}`],
            ['Spend (12 months)', crore(plan.spend_minor)], ['Addressable', plan.addressable_minor === null ? '–' : crore(plan.addressable_minor)],
            ['Budget', inr(plan.budget_minor)], ['Savings target', inr(plan.savings_target_minor)],
            ['Submitted', plan.submitted_at ? dateTime(plan.submitted_at) : '–'], ['Decision', plan.approved_at ? `approved ${dateTime(plan.approved_at)}` : plan.decision_comment ? 'with comment' : '–'],
          ]} />
          {plan.decision_comment && <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700"><span className="font-medium">Decision comment: </span>{plan.decision_comment}</p>}

          <section aria-labelledby="plan-validation">
            <h3 id="plan-validation" className="mb-1 text-sm font-semibold text-slate-900">Validation</h3>
            {plan.validation.length === 0 ? (
              <p className="text-sm text-emerald-800"><span aria-hidden>✓ </span>The plan is valid: it can be submitted and approved.</p>
            ) : (
              <ul className="list-disc space-y-0.5 pl-5 text-sm text-red-800" role="alert">{plan.validation.map((e) => <li key={e}>{e}</li>)}</ul>
            )}
          </section>

          <section aria-labelledby="plan-chain">
            <h3 id="plan-chain" className="mb-1 text-sm font-semibold text-slate-900">Approval chain</h3>
            <ol className="space-y-1 text-sm" aria-label="Approval chain">
              <ChainStep done label="Draft by the category plan owner" note={isOwner ? 'you' : undefined} />
              <ChainStep done={!!plan.submitted_at} label="Submitted for approval" note={plan.submitted_at ? dateTime(plan.submitted_at) : 'not yet'} />
              <ChainStep done={plan.status === 'APPROVED' || plan.status === 'SUPERSEDED'} active={plan.status === 'IN_APPROVAL'} label="Approved by the procurement head or CPO"
                note={plan.status === 'IN_APPROVAL' ? 'waiting for a decision' : plan.status === 'REJECTED' ? 'rejected' : undefined} />
            </ol>
            <p className="mt-2 text-xs text-slate-600">Segregation of duties: the plan owner and the person who submitted it can neither approve nor reject it; the approval task goes to a procurement head other than them.</p>
            {plan.status === 'IN_APPROVAL' && <div className="mt-3"><TaskPanel objectRef={plan.number} /></div>}
          </section>

          {mode === 'view' && (
            <>
              <section aria-labelledby="plan-levers">
                <h3 id="plan-levers" className="mb-1 text-sm font-semibold text-slate-900">Levers and savings split</h3>
                {plan.levers.length ? (
                  <ul className="grid gap-1 text-sm md:grid-cols-2">
                    {plan.levers.map((l) => <li key={l} className="flex justify-between gap-2 rounded border border-slate-200 px-3 py-1.5"><span>{l}</span><span className="tabular-nums text-slate-700">{plan.savings_by_lever?.[l] !== undefined ? inr(plan.savings_by_lever[l]) : '–'}</span></li>)}
                  </ul>
                ) : <p className="text-sm text-slate-500">No lever named.</p>}
              </section>
              <section aria-labelledby="plan-waves">
                <h3 id="plan-waves" className="mb-1 text-sm font-semibold text-slate-900">Wave plan</h3>
                {plan.wave_plan?.length ? (
                  <ol className="space-y-1 text-sm">
                    {plan.wave_plan.map((w, i) => <li key={i} className="rounded border border-slate-200 px-3 py-1.5"><span className="font-medium">{w.name}</span> · {date(w.start)} – {date(w.end)}{w.lever ? ` · ${w.lever}` : ''}{w.milestone ? ` · ${w.milestone}` : ''}</li>)}
                  </ol>
                ) : <p className="text-sm text-slate-500">{plan.waves?.length ? plan.waves.join(' · ') : 'No wave planned.'}</p>}
              </section>
            </>
          )}

          {mode === 'edit' && <EditForm plan={plan} catalogue={plan.leverCatalogue} onDone={() => setMode('view')} onCancel={() => setMode('view')} />}
          {mode === 'submit' && <CommentForm title="Submit for approval" required={false} confirm="Submit" path={`/category-plans/${encodeURIComponent(plan.number)}/submit`} success={`${plan.number} submitted for approval`} onDone={() => setMode('view')} onCancel={() => setMode('view')} />}
          {mode === 'reject' && <CommentForm title="Reject the plan" required confirm="Reject plan" danger path={`/category-plans/${encodeURIComponent(plan.number)}/reject`} success={`${plan.number} rejected`} onDone={() => setMode('view')} onCancel={() => setMode('view')} />}
          {mode === 'revise' && <CommentForm title="Revise the approved plan" required confirm="Create revision" path={`/category-plans/${encodeURIComponent(plan.number)}/revise`} success={`A new draft version of ${plan.category} was created`} onDone={() => { setMode('view'); onClose(); }} onCancel={() => setMode('view')} />}
          {mode === 'approve' && <CommentForm title="Approve the plan" required={false} confirm="Approve plan" path={`/category-plans/${encodeURIComponent(plan.number)}/approve`} success={`${plan.number} (${plan.category}) approved`} onDone={() => setMode('view')} onCancel={() => setMode('view')} />}

          {mode === 'view' && (
            <div className="flex flex-wrap gap-2">
              {editable && <Button onClick={() => setMode('edit')}>Edit plan</Button>}
              {editable && <Button variant="primary" onClick={() => setMode('submit')}>Submit for approval</Button>}
              {isDecider && (plan.status === 'DRAFT' || plan.status === 'IN_APPROVAL') && <Button variant="primary" onClick={() => setMode('approve')}>Approve</Button>}
              {isDecider && (plan.status === 'DRAFT' || plan.status === 'IN_APPROVAL') && <Button variant="danger" onClick={() => setMode('reject')}>Reject</Button>}
              {isEditor && plan.status === 'APPROVED' && <Button onClick={() => setMode('revise')}>Revise (new version)</Button>}
            </div>
          )}
          {me && mode === 'view' && !isEditor && !isDecider && <p className="text-xs text-slate-500">Your role can read plans but not change them.</p>}

          <section aria-labelledby="plan-versions">
            <h3 id="plan-versions" className="mb-1 text-sm font-semibold text-slate-900">Versions for {plan.category} {plan.fiscal_year}</h3>
            <ul className="flex flex-wrap gap-2 text-sm">
              {plan.versions.map((v) => (
                <li key={v.number} className={`rounded border px-3 py-1.5 ${v.number === plan.number ? 'border-[#1A56DB] bg-blue-50' : 'border-slate-200'}`}>
                  <span className="font-mono text-xs">{v.number}</span> · v{v.version} · <StatusChip status={v.status} />
                </li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="plan-links">
            <h3 id="plan-links" className="mb-1 text-sm font-semibold text-slate-900">Pipeline of {plan.category}</h3>
            {links.isLoading ? <Loading /> : links.error ? <ProblemBox error={links.error} /> : links.data && (
              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Sourcing events</p>
                  {links.data.sourcingEvents.length ? (
                    <ul className="mt-1 space-y-1 text-sm">
                      {links.data.sourcingEvents.map((e) => <li key={e.number}><Link href={`/pic/sourcing/${encodeURIComponent(e.number)}`} className="font-mono text-xs font-medium text-[#1A56DB] hover:underline">{e.number}</Link> {e.title} <StatusChip status={e.status} /></li>)}
                    </ul>
                  ) : <p className="mt-1 text-sm text-slate-500">None yet.</p>}
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Savings initiatives</p>
                  {links.data.savingsInitiatives.length ? (
                    <ul className="mt-1 space-y-1 text-sm">
                      {links.data.savingsInitiatives.map((i) => <li key={i.number}><Link href="/pic/savings" className="font-mono text-xs font-medium text-[#1A56DB] hover:underline">{i.number}</Link> {i.title} <StatusChip status={i.stage} /></li>)}
                    </ul>
                  ) : <p className="mt-1 text-sm text-slate-500">None yet.</p>}
                </div>
              </div>
            )}
          </section>
          <div className="flex justify-end"><Button onClick={onClose}>Close</Button></div>
        </div>
      )}
    </Dialog>
  );
}

function ChainStep({ done, active, label: text, note }: { done?: boolean; active?: boolean; label: string; note?: string }) {
  return (
    <li className="flex items-center gap-2">
      <span aria-hidden className={`inline-flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold ${done ? 'bg-emerald-100 text-emerald-800' : active ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-500'}`}>{done ? '✓' : active ? '…' : '○'}</span>
      <span className={done || active ? 'text-slate-900' : 'text-slate-500'}>{text}</span>
      {note && <span className="text-xs text-slate-500">· {note}</span>}
      <span className="sr-only">{done ? 'done' : active ? 'in progress' : 'pending'}</span>
    </li>
  );
}

function CommentForm({ title, required, confirm, danger, path, success, onDone, onCancel }: {
  title: string; required: boolean; confirm: string; danger?: boolean; path: string; success: string; onDone: () => void; onCancel: () => void;
}) {
  const [comment, setComment] = useState('');
  const run = useCommand(() => api.post(path, { comment: comment.trim() || undefined }), { success, onSuccess: onDone });
  return (
    <section className="rounded-lg border border-slate-200 p-4" aria-label={title}>
      <h3 className="mb-2 text-sm font-semibold text-slate-900">{title}</h3>
      <Field label={required ? 'Comment (required, at least 5 characters)' : 'Comment (optional)'} required={required}>{(id) => <Textarea id={id} value={comment} onChange={(e) => setComment(e.target.value)} />}</Field>
      {run.error && <div className="mt-3"><ProblemBox error={run.error} /></div>}
      <div className="mt-3 flex justify-end gap-2">
        <Button onClick={onCancel}>Cancel</Button>
        <Button variant={danger ? 'danger' : 'primary'} disabled={required && comment.trim().length < 5} busy={run.isPending} onClick={() => run.mutate()}>{confirm}</Button>
      </div>
    </section>
  );
}

function EditForm({ plan, catalogue, onDone, onCancel }: { plan: PlanDetail; catalogue: string[]; onDone: () => void; onCancel: () => void }) {
  const [budget, setBudget] = useState(minorToRupees(plan.budget_minor));
  const [target, setTarget] = useState(minorToRupees(plan.savings_target_minor));
  const [levers, setLevers] = useState<string[]>(plan.levers);
  const [manual, setManual] = useState(false);
  const [split, setSplit] = useState<Record<string, string>>(Object.fromEntries(Object.entries(plan.savings_by_lever ?? {}).map(([k, v]) => [k, minorToRupees(v)])));
  const [waves, setWaves] = useState<Wave[]>(plan.wave_plan?.length ? plan.wave_plan : []);
  const options = [...new Set([...catalogue, ...levers])];
  const num = (text: string) => (text.trim() !== '' && Number.isFinite(Number(text)) && Number(text) >= 0 ? rupeesToMinor(text) : null);
  const budgetMinor = num(budget);
  const targetMinor = num(target);
  const splitTotal = levers.reduce((s, l) => s + (num(split[l] ?? '') ?? 0), 0);
  const splitOk = !manual || (targetMinor !== null && splitTotal === targetMinor);
  const save = useCommand(() => api.patch<PlanRow>(`/category-plans/${encodeURIComponent(plan.number)}`, {
    budget_minor: budgetMinor, savings_target_minor: targetMinor, levers, wave_plan: waves.map((w) => ({ name: w.name.trim(), start: w.start, end: w.end, ...(w.lever ? { lever: w.lever } : {}), ...(w.milestone ? { milestone: w.milestone } : {}) })),
    ...(manual ? { savings_by_lever: Object.fromEntries(levers.map((l) => [l, num(split[l] ?? '') ?? 0])) } : {}),
  }), { success: `${plan.number} saved`, onSuccess: onDone });
  const setWave = (i: number, patch: Partial<Wave>) => setWaves((cur) => cur.map((w, j) => (j === i ? { ...w, ...patch } : w)));

  return (
    <section className="space-y-3 rounded-lg border border-slate-200 p-4" aria-label="Edit plan">
      <h3 className="text-sm font-semibold text-slate-900">Edit plan</h3>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Budget (₹)" required hint="Zero or more" error={budgetMinor === null ? 'Enter an amount' : undefined}>{(id, d) => <Input id={id} aria-describedby={d} inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value)} />}</Field>
        <Field label="Savings target (₹)" required hint={`At most the budget and the plan cap of the addressable spend${plan.addressable_minor ? ` (${crore(plan.addressable_minor)})` : ''}`} error={targetMinor === null ? 'Enter an amount' : undefined}>
          {(id, d) => <Input id={id} aria-describedby={d} inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} />}
        </Field>
      </div>
      <fieldset>
        <legend className="mb-1 text-xs font-medium text-slate-700">Levers (from the catalogue)</legend>
        <div className="flex flex-wrap gap-2">
          {options.map((l) => (
            <label key={l} className={`inline-flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1 text-sm focus-within:ring-2 focus-within:ring-[#1A56DB] ${levers.includes(l) ? 'border-[#1A56DB] bg-blue-50 text-[#1A56DB]' : 'border-slate-300 bg-white text-slate-700'}`}>
              <input type="checkbox" className="accent-[#1A56DB]" checked={levers.includes(l)} onChange={() => setLevers((cur) => (cur.includes(l) ? cur.filter((x) => x !== l) : [...cur, l]))} />{l}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-[#1A56DB]" checked={manual} onChange={(e) => setManual(e.target.checked)} /> Set the savings split by lever myself (otherwise it is split evenly)</label>
      {manual && (
        <div className="grid gap-2 md:grid-cols-2">
          {levers.map((l) => <Field key={l} label={`${l} (₹)`}>{(id) => <Input id={id} inputMode="decimal" value={split[l] ?? ''} onChange={(e) => setSplit((cur) => ({ ...cur, [l]: e.target.value }))} />}</Field>)}
          <p className={`text-xs md:col-span-2 ${splitOk ? 'text-slate-500' : 'text-red-700'}`} role={splitOk ? undefined : 'alert'}>Split adds up to {inr(splitTotal)}; it must equal the target {targetMinor === null ? '' : inr(targetMinor)}.</p>
        </div>
      )}
      <div>
        <div className="mb-1 flex items-center justify-between"><p className="text-xs font-medium text-slate-700">Wave plan</p>
          <Button onClick={() => setWaves((cur) => [...cur, { name: '', start: '', end: '', lever: levers[0] }])}>Add wave</Button></div>
        {!waves.length && <p className="text-sm text-slate-500">No wave yet: the plan needs at least one dated wave.</p>}
        <ul className="space-y-2">
          {waves.map((w, i) => (
            <li key={i} className="grid gap-2 rounded border border-slate-200 p-2 md:grid-cols-5">
              <Field label="Name">{(id) => <Input id={id} value={w.name} onChange={(e) => setWave(i, { name: e.target.value })} />}</Field>
              <Field label="Start">{(id) => <Input id={id} type="date" value={w.start} onChange={(e) => setWave(i, { start: e.target.value })} />}</Field>
              <Field label="End">{(id) => <Input id={id} type="date" value={w.end} onChange={(e) => setWave(i, { end: e.target.value })} />}</Field>
              <Field label="Milestone">{(id) => <Input id={id} value={w.milestone ?? ''} onChange={(e) => setWave(i, { milestone: e.target.value })} />}</Field>
              <div className="flex items-end"><Button variant="ghost" onClick={() => setWaves((cur) => cur.filter((_, j) => j !== i))} aria-label={`Remove wave ${i + 1}`}>Remove</Button></div>
            </li>
          ))}
        </ul>
      </div>
      {save.error && <ProblemBox error={save.error} />}
      <div className="flex justify-end gap-2">
        <Button onClick={onCancel}>Cancel</Button>
        <Button variant="primary" disabled={budgetMinor === null || targetMinor === null || !splitOk || !levers.length} busy={save.isPending} onClick={() => save.mutate()}>Save plan</Button>
      </div>
    </section>
  );
}
