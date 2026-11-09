'use client';

import { Fragment, useEffect, useState } from 'react';
import { Button, Dialog, Empty, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api, ApiError, readSessionUser } from '@/lib/pic/api';
import { inr, label, qty } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { CompareRow, Comparison, ifMatchOptions, useEventCommand } from '../_lib';

// ---------------------------------------------------------------- shapes (GET /sourcing/events/{ref}, POST …/scenarios)
export type EventLine = { id: string; line_no: number; description: string; plant: string; annual_qty: string; monthly_qty: string; uom: string;
  requisition_id: string | null; pr_line_no: number | null; lot_code?: string | null; baseline_price_minor?: number | null; requisition?: string | null; need_date?: string | null };
export type Criterion = { id: string; code: string; name: string; weight: number; data_source?: string; min_score?: string | number | null };
export type Invitee = { id: string; code: string; name: string; categoryStatus: string; waiver: string | null };
export type BidMeta = { supplier: string; round: number; status: string; submittedAt: string; hash: string };
export type ScenarioRaw = Record<string, unknown> & { id: string; kind: string; feasible: boolean; allocations: Allocation[]; explanation: Record<string, unknown> | null };
export type AllocLine = { line: number; eventLineId: string; lot: string | null; bundle: boolean; share: string; monthlyQty: string; annualQty: string;
  priceMinor: number; tcoMinor: number; valueMinor: number };
/** One supplier of a scenario. A single-line event carries the price and quantity directly; several lines carry `lines` and the award value. */
export type Allocation = { supplier: string; supplierId: string; share: string; monthlyQty?: string; annualQty?: string | null; priceMinor: number | null;
  tcoMinor?: number; valueMinor?: number; lines?: AllocLine[] };
export type Scenario = { id: string; kind: string; feasible: boolean; allocations: Allocation[]; weightedPriceMinor: number | null;
  weightedTcoMinor: number | null; annualSavingsMinor: number | null; riskScore: number | null; superseded: string | null; explanation: Record<string, unknown> | null };
export type AwardAuthority = { valueMinor: number; chain: string[]; bandChain: string[]; approvalAboveMinor: number; rule: string };
/** An expired offer the award was proposed on anyway (D5): the written override recorded on the decision (exception BID_OFFER_EXPIRED). */
export type ExpiredOverride = { by?: string; byEmail?: string; byName?: string; at?: string; reason: string; bids: ExpiredBid[] };
export type ExpiredBid = { supplier: string; supplierName?: string | null; validUntil: string; round?: number; daysExpired?: number };
export type AwardException = { code: string; detail: string; override?: ExpiredOverride };
export type AwardDecision = { id: string; scenario_id: string; status: string; rationale: string | null; conflict_declarations: { user: string; declaration: string }[];
  annual_value_minor: number; rule_set_version: string; created_at: string; authority?: AwardAuthority | null; exceptions?: AwardException[]; regret_sent_at?: string | null };
export type ShouldCost = { model: string; material: string; conversion: string; tooling: string; packaging: string; subtotal: string;
  overheadMarginPct: string; unitCost: string; unitCostMinor: number };
export type BudgetCheck = { outcome: string; fiscalYear?: string; plan?: string; mode?: string; budgetMinor?: number; committedMinor?: number; eventEstimateMinor?: number;
  incrementalMinor?: number; projectedMinor?: number; usedPct?: string; justification?: string };
export type SourcingEvent = {
  id: string; number: string; type: string; title: string; category: string; status: string; round: number; weights_locked: boolean; owner_id?: string;
  published_at: string | null; close_at: string; closed_at: string | null; unsealed_at: string | null; baseline_price_minor: number | null;
  baseline_method: string | null; should_cost: ShouldCost | null; constraints: ({ max_suppliers?: number; max_share?: string; min_share?: string } & Record<string, unknown>) | null;
  tco_params: Record<string, unknown> | null; savings_target_pct: string | null; bundle?: { kind: string; ref: string | null; requisitions: string[]; sourceLines: number } | null;
  auction?: Record<string, unknown> | null; auction_ends_at?: string | null;
  currency?: string; scoring_method?: string; purpose_code?: string | null; need_date?: string | null; budget_check?: BudgetCheck | null; budget_justification?: string | null;
  clarification_close_at?: string | null; reference_date?: string | null; min_bidders?: number | null; competitive?: boolean | null;
  opening?: { required?: boolean; round?: number; openers?: string[] } | null; template_code?: string | null; cloned_from?: string | null;
  rule_versions?: Record<string, string> | null; open_at?: string | null;
  lines: EventLine[]; criteria: Criterion[]; invitees: Invitee[]; bids: BidMeta[]; scenarios: ScenarioRaw[]; awardDecisions: AwardDecision[];
};
export type LineBid = { supplier: string; rank: number; priceMinor: number; tcoMinor: number; leadTimeDays: number; paymentTermsDays: number;
  verifiedCapacityPerMonth: string | null; weightedScore?: string };
export type LineMatrix = { line: number; description: string; lot: string | null; uom: string; annualQty: string; monthlyQty: string; baselineMinor: number | null; bids: LineBid[] };

/** Persisted scenarios come back snake_case on the event, fresh ones camelCase from POST …/scenarios. */
export function normaliseScenario(s: ScenarioRaw): Scenario {
  const pick = (a: string, b: string) => (s[a] ?? s[b] ?? null) as number | null;
  const explanation = s.explanation as Record<string, unknown> | null;
  const by = explanation?.supersededBy;
  return { id: s.id, kind: s.kind, feasible: s.feasible, allocations: s.allocations ?? [], explanation,
    weightedPriceMinor: pick('weightedPriceMinor', 'weighted_price_minor'), weightedTcoMinor: pick('weightedTcoMinor', 'weighted_tco_minor'),
    annualSavingsMinor: pick('annualSavingsMinor', 'annual_savings_minor'), riskScore: pick('riskScore', 'risk_score'),
    superseded: explanation?.supersededAt ? String(by ?? 'rebuilt') : null };
}

export function toLocalInput(d: Date) {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

const pct = (v: string | number | null | undefined, digits = 0) => (v === null || v === undefined || v === '' ? '–' : `${(Number(v) * 100).toFixed(digits)}%`);

/** The evaluation matrix by line: every bid on each line, ranked by TCO. */
export function LineMatrixPanel({ event }: { event: SourcingEvent }) {
  const lines = useApi<LineMatrix[]>(`/sourcing/events/${encodeURIComponent(event.number)}/line-matrix`);
  if (lines.isLoading) return <Loading />;
  if (lines.error) return <ProblemBox error={lines.error} />;
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">By line and lot</h3>
      <div className="space-y-3">
        {(lines.data ?? []).map((l) => (
          <div key={l.line} className="overflow-x-auto rounded-lg border border-slate-200">
            <p className="border-b border-slate-100 bg-slate-50 px-3 py-2 text-sm">
              <span className="font-mono text-xs text-slate-500">Line {l.line}</span> <span className="font-medium">{l.description}</span>
              {l.lot && <span className="ml-2 rounded bg-violet-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-violet-800">lot {l.lot}</span>}
              <span className="ml-2 text-slate-600">· {qty(l.annualQty, l.uom)} a year{l.baselineMinor ? ` · baseline ${inr(l.baselineMinor)}` : ''}</span>
            </p>
            {l.bids.length === 0 ? <p className="px-3 py-2 text-sm text-amber-800">Nobody bid this line – it cannot be awarded.</p> : (
              <table className="min-w-full text-sm">
                <thead className="text-left text-[11px] uppercase tracking-wide text-slate-500"><tr><th scope="col" className="px-3 py-1">#</th><th scope="col" className="px-3 py-1">Supplier</th><th scope="col" className="px-3 py-1 text-right">Price</th>
                  <th scope="col" className="px-3 py-1 text-right">TCO / unit</th><th scope="col" className="px-3 py-1 text-right">Lead time</th><th scope="col" className="px-3 py-1 text-right">Capacity / month</th><th scope="col" className="px-3 py-1 text-right">Score</th></tr></thead>
                <tbody className="divide-y divide-slate-100">{l.bids.map((b) => (
                  <tr key={b.supplier}><td className="px-3 py-1 tabular-nums">{b.rank}</td><td className="px-3 py-1 font-medium">{b.supplier}</td><td className="px-3 py-1 text-right tabular-nums">{inr(b.priceMinor)}</td>
                    <td className="px-3 py-1 text-right tabular-nums">{inr(b.tcoMinor)}</td><td className="px-3 py-1 text-right tabular-nums">{b.leadTimeDays} d</td>
                    <td className="px-3 py-1 text-right tabular-nums">{qty(b.verifiedCapacityPerMonth)}</td><td className="px-3 py-1 text-right tabular-nums">{b.weightedScore ?? '–'}</td></tr>
                ))}</tbody>
              </table>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- award scenarios side by side
export function ScenariosPanel({ event, scenarios, canAward, canManage, onAward, onCustom }: {
  event: SourcingEvent; scenarios: Scenario[]; canAward: boolean; canManage: boolean; onAward: (id: string) => void; onCustom: () => void;
}) {
  const line = event.lines[0];
  const multi = event.lines.length > 1;
  return (
    <div className="space-y-5">
      {canManage && event.status === 'UNDER_EVALUATION' && (
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={onCustom}>Enter a custom split</Button>
          <p className="text-xs text-slate-500">A manual split by percentage or monthly quantity per supplier, checked against capacity, MOQ, share bounds and the risk caps. The shares of each line must add up to exactly 100 %.</p>
        </div>
      )}
      {!scenarios.length ? (
        <Empty title="No award scenarios yet" hint="After the opening, build scenarios to compare lowest cost, best value and the capacity-constrained optimum." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          {scenarios.map((s) => {
            const decision = event.awardDecisions.find((d) => d.scenario_id === s.id);
            const violations = (s.explanation?.violations as string[] | undefined) ?? [];
            return (
              <article key={s.id} aria-label={`${label(s.kind)} scenario`} className={`flex flex-col rounded-xl border p-4 ${s.superseded ? 'border-slate-200 bg-slate-50 opacity-80' : s.feasible ? 'border-slate-200' : 'border-red-200 bg-red-50/30'}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold">{label(s.kind)}</h3>
                  <span className="flex flex-wrap gap-1">
                    {s.superseded && <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[11px] font-semibold uppercase text-slate-700" title={s.superseded}>Stale</span>}
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ring-1 ring-inset ${s.feasible ? 'bg-emerald-50 text-emerald-800 ring-emerald-200' : 'bg-red-50 text-red-800 ring-red-200'}`}>
                      {s.feasible ? 'Feasible' : 'Infeasible'}
                    </span>
                  </span>
                </div>
                {s.superseded && <p className="mt-1 text-xs text-slate-600">Superseded: {s.superseded}. Rebuild the scenarios; this one cannot be awarded.</p>}
                <table className="mt-3 w-full text-sm">
                  <thead className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                    <tr><th scope="col" className="py-1">Supplier</th><th scope="col" className="py-1 text-right">Share</th><th scope="col" className="py-1 text-right">{multi ? 'Lines' : 'Qty / month'}</th><th scope="col" className="py-1 text-right">{multi ? 'Annual value' : 'Price'}</th></tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {s.allocations.length ? s.allocations.map((a) => (
                      <Fragment key={a.supplier}>
                        <tr>
                          <td className="py-1 font-medium">{a.supplier}</td>
                          <td className="py-1 text-right tabular-nums">{pct(a.share)}</td>
                          <td className="py-1 text-right tabular-nums" title={a.annualQty ? `${qty(a.annualQty)} per year` : undefined}>{a.lines ? a.lines.length : qty(a.monthlyQty)}</td>
                          <td className="py-1 text-right tabular-nums">{inr(a.lines ? a.valueMinor : a.priceMinor)}</td>
                        </tr>
                        {a.lines?.map((l) => (
                          <tr key={`${a.supplier}-${l.line}`} className="text-xs text-slate-600">
                            <td className="py-0.5 pl-3">line {l.line}{l.lot ? ` · lot ${l.lot}${l.bundle ? ' bundle' : ''}` : ''}</td>
                            <td className="py-0.5 text-right tabular-nums">{pct(l.share)}</td>
                            <td className="py-0.5 text-right tabular-nums" title={`${qty(l.annualQty)} per year`}>{qty(l.monthlyQty)} / month</td>
                            <td className="py-0.5 text-right tabular-nums">{inr(l.priceMinor)} / unit</td>
                          </tr>
                        ))}
                      </Fragment>
                    )) : <tr><td colSpan={4} className="py-2 text-slate-500">No allocation possible</td></tr>}
                  </tbody>
                </table>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
                  <div><dt className="text-xs text-slate-500">{multi ? 'Annual award value' : 'Weighted price'}</dt><dd className="font-semibold tabular-nums">{inr(s.weightedPriceMinor)}</dd></div>
                  <div><dt className="text-xs text-slate-500">{multi ? 'Annual TCO' : 'Weighted TCO'}</dt><dd className="font-semibold tabular-nums">{inr(s.weightedTcoMinor)}</dd></div>
                  <div><dt className="text-xs text-slate-500">Risk score (0 best, 100 worst)</dt><dd className="font-semibold tabular-nums">{s.riskScore ?? '–'}</dd></div>
                  <div><dt className="text-xs text-slate-500">Annual savings vs baseline {event.baseline_price_minor ? inr(event.baseline_price_minor) : ''}{!multi && line ? ` × ${qty(line.annual_qty, line.uom)}` : ''}</dt>
                    <dd className={`font-semibold tabular-nums ${s.annualSavingsMinor && s.annualSavingsMinor > 0 ? 'text-emerald-700' : s.annualSavingsMinor && s.annualSavingsMinor < 0 ? 'text-red-700' : ''}`}>{inr(s.annualSavingsMinor)}{s.annualSavingsMinor != null && s.annualSavingsMinor < 0 ? ' (cost increase)' : ''}</dd></div>
                </dl>
                {violations.length > 0 && (
                  <ul className="mt-2 list-disc rounded bg-red-50 p-2 pl-5 text-xs text-red-800" aria-label="Why this scenario is infeasible">{violations.map((v) => <li key={v}>{v}</li>)}</ul>
                )}
                {s.explanation && <Explanation e={s.explanation} />}
                <div className="mt-auto pt-3">
                  {decision && <p className="mb-2 flex items-center gap-2 text-xs">Award decision <StatusChip status={decision.status} /></p>}
                  {canAward && s.feasible && !s.superseded && <Button variant="primary" className="w-full" onClick={() => onAward(s.id)}>Award this scenario</Button>}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

type RiskCheck = { rule: string; limit: string | number; ok: boolean; top?: string; topSharePct?: string; conditionalSharePct?: string; suppliers?: number };
function Explanation({ e }: { e: Record<string, unknown> }) {
  const bounds = e.bounds as Record<string, string> | undefined;
  const lots = e.lots as { lot: string; decision: string }[] | undefined;
  const risk = e.risk as { excluded: { supplierId: string; reason: string }[]; checks: RiskCheck[] } | undefined;
  return (
    <div className="mt-3 rounded-lg bg-slate-50 p-2 text-xs text-slate-600">
      {typeof e.rule === 'string' && <p><span className="font-semibold">Rule:</span> {e.rule}</p>}
      {typeof e.capacityCheck === 'string' && <p><span className="font-semibold">Capacity:</span> {e.capacityCheck}</p>}
      {typeof e.Q === 'string' && <p><span className="font-semibold">Demand Q:</span> {qty(e.Q)} / month</p>}
      {bounds && <ul className="mt-1 font-mono text-[11px]">{Object.entries(bounds).map(([k, v]) => <li key={k}>{k}: {v}</li>)}</ul>}
      {lots && lots.length > 0 && <p className="mt-1"><span className="font-semibold">Lots:</span> {lots.map((l) => `${l.lot} ${l.decision === 'BUNDLE' ? 'awarded as a bundle' : 'split by line'}`).join('; ')}</p>}
      {risk && risk.excluded.length > 0 && <p className="mt-1 text-amber-800"><span className="font-semibold">Left out:</span> {risk.excluded.map((x) => x.reason).join('; ')}</p>}
      {risk && risk.checks.map((c) => (
        <p key={c.rule} className={c.ok ? 'mt-1 text-emerald-800' : 'mt-1 font-semibold text-red-700'}>
          {c.ok ? '✓' : '✗'} {label(c.rule)}: limit {String(c.limit)}{c.topSharePct ? `, largest ${String(c.top)} ${c.topSharePct}%` : ''}{c.conditionalSharePct ? `, conditional ${c.conditionalSharePct}%` : ''}{c.suppliers ? `, ${c.suppliers} supplier(s)` : ''}
        </p>
      ))}
      {Array.isArray(e.uncovered) && e.uncovered.length > 0 && <p className="mt-1 text-red-700">No bid on line(s) {(e.uncovered as number[]).join(', ')}.</p>}
    </div>
  );
}

// ---------------------------------------------------------------- custom split
type SplitRow = { supplier: string; line: string; mode: 'share' | 'qty'; value: string };

export function CustomSplitDialog({ event, rows, onClose }: { event: SourcingEvent; rows: CompareRow[]; onClose: () => void }) {
  const path = `/sourcing/events/${encodeURIComponent(event.number)}`;
  const multi = event.lines.length > 1;
  const [split, setSplit] = useState<SplitRow[]>([
    { supplier: rows[0]?.supplier ?? '', line: multi ? String(event.lines[0].line_no) : '', mode: 'share', value: '60' },
    { supplier: rows[1]?.supplier ?? rows[0]?.supplier ?? '', line: multi ? String(event.lines[0].line_no) : '', mode: 'share', value: '40' },
  ]);
  const [result, setResult] = useState<Scenario | null>(null);
  const set = (i: number, patch: Partial<SplitRow>) => setSplit((cur) => cur.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const totals = new Map<string, number>();
  split.forEach((r) => { if (r.mode === 'share') totals.set(r.line || '1', (totals.get(r.line || '1') ?? 0) + (Number(r.value) || 0)); });
  const shareProblems = [...totals].filter(([, t]) => Math.abs(t - 100) > 0.0001).map(([ln, t]) => `${multi ? `Line ${ln}: ` : ''}shares add up to ${t}, not 100`);
  const invalid = split.some((r) => !r.supplier || !(Number(r.value) > 0) || (multi && !r.line)) || shareProblems.length > 0;
  const go = useEventCommand(path, (_: void, ifMatch) => api.post<ScenarioRaw>(`${path}/scenarios/custom`, {
    allocations: split.map((r) => ({ supplier: r.supplier, ...(multi ? { line: Number(r.line) } : {}), ...(r.mode === 'share' ? { share_pct: r.value } : { qty_per_month: r.value }) })),
  }, ifMatchOptions(ifMatch)), {
    success: (s) => (s.feasible ? 'Custom scenario stored: feasible' : 'Custom scenario stored: NOT feasible, see the reasons'),
    onSuccess: (s) => setResult(normaliseScenario(s)),
  });
  return (
    <Dialog open title="Custom award split" onClose={onClose} wide>
      <div className="space-y-3">
        <p className="text-sm text-slate-700">Enter percentages of the monthly demand (or monthly quantities) per bidder{multi ? ' and line' : ''}. The scenario is stored with its risk score and reasons whether it is feasible or not.</p>
        <div className="space-y-2">
          {split.map((r, i) => (
            <div key={i} className="grid grid-cols-2 items-end gap-2 md:grid-cols-[1.5fr_1fr_1fr_1fr_auto]">
              <Field label={i === 0 ? 'Bidder' : ' '}>{(id) => <Select id={id} aria-label={`Allocation ${i + 1} bidder`} value={r.supplier} onChange={(e) => set(i, { supplier: e.target.value })}
                options={rows.map((b) => ({ value: b.supplier, label: `${b.supplier} · ${inr(b.tcoMinor)}` }))} />}</Field>
              {multi ? <Field label={i === 0 ? 'Line' : ' '}>{(id) => <Select id={id} aria-label={`Allocation ${i + 1} line`} value={r.line} onChange={(e) => set(i, { line: e.target.value })}
                options={event.lines.map((l) => ({ value: String(l.line_no), label: `Line ${l.line_no}` }))} />}</Field> : <div className="hidden md:block" />}
              <Field label={i === 0 ? 'Split by' : ' '}>{(id) => <Select id={id} aria-label={`Allocation ${i + 1} basis`} value={r.mode} onChange={(e) => set(i, { mode: e.target.value as SplitRow['mode'] })}
                options={[{ value: 'share', label: 'Percentage' }, { value: 'qty', label: 'Qty / month' }]} />}</Field>
              <Field label={i === 0 ? (r.mode === 'share' ? 'Share (%)' : 'Quantity / month') : ' '}>{(id) => <Input id={id} aria-label={`Allocation ${i + 1} value`} type="number" min="0" step="any" value={r.value} onChange={(e) => set(i, { value: e.target.value })} />}</Field>
              <Button variant="ghost" aria-label={`Remove allocation ${i + 1}`} disabled={split.length < 2} onClick={() => setSplit((cur) => cur.filter((_, j) => j !== i))}>Remove</Button>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => setSplit((cur) => [...cur, { supplier: rows[0]?.supplier ?? '', line: multi ? String(event.lines[0].line_no) : '', mode: 'share', value: '' }])}>Add allocation</Button>
          {shareProblems.length > 0 && <p role="alert" className="text-sm text-red-700">{shareProblems.join('; ')}</p>}
        </div>
        {result && (
          <div role="status" className={`rounded-lg border p-3 text-sm ${result.feasible ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : 'border-red-200 bg-red-50 text-red-900'}`}>
            <p className="font-semibold">{result.feasible ? 'Feasible' : 'Not feasible'} · risk score {result.riskScore ?? '–'} · savings {inr(result.annualSavingsMinor)} a year</p>
            {((result.explanation?.violations as string[] | undefined) ?? []).map((v) => <p key={v}>{v}</p>)}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Close</Button>
          <Button variant="primary" disabled={invalid} busy={go.isPending} onClick={() => go.mutate()}>Check and store scenario</Button>
        </div>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- dialogs
export function ScoreDialog({ event, matrix, onClose }: { event: SourcingEvent; matrix: { supplier: string; scores?: Record<string, string> }[]; onClose: () => void }) {
  const path = `/sourcing/events/${encodeURIComponent(event.number)}`;
  const manual = event.criteria.filter((c) => c.code !== 'PRICE_TCO' && (c.data_source ?? 'MANUAL') === 'MANUAL');
  const [scores, setScores] = useState<Record<string, string>>({});
  const [comments, setComments] = useState<Record<string, string>>({});
  const entries = matrix.flatMap((m) => manual.filter((c) => (scores[`${m.supplier}|${c.code}`] ?? '') !== '').map((c) => ({
    supplier: m.supplier, criterion: c.code, score: Number(scores[`${m.supplier}|${c.code}`]), comment: comments[m.supplier] || undefined,
  })));
  const invalid = entries.some((e) => Number.isNaN(e.score) || e.score < 0 || e.score > 100);
  const save = useEventCommand(path, (_: void, ifMatch) => api.post(`${path}/scores`, entries, ifMatchOptions(ifMatch)),
    { success: `${entries.length} score(s) recorded`, onSuccess: onClose });
  return (
    <Dialog open title={`Score bids – ${event.number}`} onClose={onClose} wide>
      {!manual.length ? <Empty title="No manually scored criteria" hint="This event is scored on price/TCO and platform data only." /> : (
        <>
          <p className="mb-3 text-sm text-slate-600">Enter your own evaluation (0–100) per criterion. Price/TCO is computed from the bids and is not scored by hand. Leave a cell empty to skip it. You must have declared your conflict of interest first.</p>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                <tr><th scope="col" className="py-1 pr-2">Supplier</th>{manual.map((c) => <th scope="col" key={c.code} className="py-1 pr-2">{c.name} <span className="normal-case text-slate-400">({c.weight}%{c.min_score != null ? `, gate ${String(c.min_score)}` : ''})</span></th>)}<th scope="col" className="py-1">Comment</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {matrix.map((m) => (
                  <tr key={m.supplier} className="align-top">
                    <td className="py-2 pr-2 font-medium">{m.supplier}</td>
                    {manual.map((c) => {
                      const k = `${m.supplier}|${c.code}`;
                      return (
                        <td key={c.code} className="py-2 pr-2">
                          <Input aria-label={`${c.name} score for ${m.supplier}`} type="number" min="0" max="100" step="1" className="w-20"
                            placeholder={m.scores?.[c.code] ?? ''} value={scores[k] ?? ''} onChange={(e) => setScores((p) => ({ ...p, [k]: e.target.value }))} />
                        </td>
                      );
                    })}
                    <td className="py-2"><Input aria-label={`Comment for ${m.supplier}`} value={comments[m.supplier] ?? ''} onChange={(e) => setComments((p) => ({ ...p, [m.supplier]: e.target.value }))} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {invalid && <p role="alert" className="mt-2 text-sm text-red-700">Scores must be between 0 and 100.</p>}
        </>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!entries.length || invalid} busy={save.isPending} onClick={() => save.mutate()}>Save scores</Button>
      </div>
    </Dialog>
  );
}

export function RoundDialog({ event, onClose }: { event: SourcingEvent; onClose: () => void }) {
  const path = `/sourcing/events/${encodeURIComponent(event.number)}`;
  const [closeAt, setCloseAt] = useState(() => toLocalInput(new Date(Date.now() + 3 * 864e5)));
  const [note, setNote] = useState('');
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);
  const when = new Date(closeAt);
  const future = !Number.isNaN(when.getTime()) && when.getTime() > now;
  const go = useEventCommand(path, (_: void, ifMatch) => api.post(`${path}/rounds`, { close_at: when.toISOString(), note }, ifMatchOptions(ifMatch)),
    { success: `Round ${event.round + 1} opened – bids sealed again`, onSuccess: onClose });
  return (
    <Dialog open title={`Open negotiation round ${event.round + 1}`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="New close date-time">{(id) => <Input id={id} type="datetime-local" value={closeAt} onChange={(e) => setCloseAt(e.target.value)} />}</Field>
        <div className="md:col-span-2"><Field label="Note to bidders / reason">{(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Improve price against should-cost" />}</Field></div>
      </div>
      {!future && <p role="alert" className="mt-2 text-sm text-red-700">The close time must be in the future.</p>}
      <p className="mt-3 text-xs text-slate-500">Invited suppliers can submit a revised sealed bid. A supplier&apos;s earlier-round bid is superseded only if they bid again.</p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!future} busy={go.isPending} onClick={() => go.mutate()}>Open round</Button>
      </div>
    </Dialog>
  );
}

/** Move the bid deadline of a published / open event later; every invited supplier is notified (flow fixes F3). */
export function ExtendDialog({ event, onClose }: { event: SourcingEvent; onClose: () => void }) {
  const path = `/sourcing/events/${encodeURIComponent(event.number)}`;
  const [closeAt, setCloseAt] = useState(() => toLocalInput(new Date(new Date(event.close_at).getTime() + 2 * 864e5)));
  const [reason, setReason] = useState('');
  const when = new Date(closeAt);
  const later = !Number.isNaN(when.getTime()) && when.getTime() > new Date(event.close_at).getTime();
  const go = useEventCommand(path, (_: void, ifMatch) => api.post(`${path}/extend`, { close_at: when.toISOString(), reason: reason.trim() }, ifMatchOptions(ifMatch)),
    { success: 'Deadline extended – the invited suppliers were notified', onSuccess: onClose });
  return (
    <Dialog open title={`Extend the bid deadline of ${event.number}`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="New close date-time">{(id) => <Input id={id} type="datetime-local" value={closeAt} onChange={(e) => setCloseAt(e.target.value)} />}</Field>
        <div className="md:col-span-2"><Field label="Reason (sent to the suppliers) *">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Suppliers asked for time to submit samples" />}</Field></div>
      </div>
      {!later && <p role="alert" className="mt-2 text-sm text-red-700">A deadline can only move later than the current one.</p>}
      <p className="mt-3 text-xs text-slate-500">Bids already submitted stay sealed and valid; suppliers may replace them until the new deadline.</p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!later || reason.trim().length < 3} busy={go.isPending} onClick={() => go.mutate()}>Extend deadline</Button>
      </div>
    </Dialog>
  );
}

/** What the server will flag for this scenario, worked out from the comparison so the buyer sees it before proposing. */
export function previewExceptions(event: SourcingEvent, scenario: Scenario | undefined, comparison: Comparison | undefined): { code: string; detail: string; needsRationale: boolean }[] {
  if (!scenario || !comparison) return [];
  const rows = comparison.bids;
  const by = new Map(rows.map((r) => [r.supplier, r]));
  const out: { code: string; detail: string; needsRationale: boolean }[] = [];
  const eligible = rows.filter((r) => !r.technicalGate || r.technicalGate.passed);
  const pool = eligible.length ? eligible : rows;
  const multi = event.lines.length > 1;
  let notLowest = false;
  if (multi) {
    const lowest: Record<number, number> = {};
    pool.forEach((r) => r.lines.forEach((l) => { lowest[l.line] = Math.min(lowest[l.line] ?? l.priceMinor, l.priceMinor); }));
    notLowest = scenario.allocations.some((a) => a.lines?.some((l) => l.priceMinor > (lowest[l.line] ?? 0)));
  } else if (pool.length) {
    const low = Math.min(...pool.map((r) => r.priceMinor));
    notLowest = scenario.allocations.some((a) => (a.priceMinor ?? 0) > low);
  }
  if (notLowest) out.push({ code: 'NOT_LOWEST', detail: 'The award includes a bid that is not the lowest eligible price.', needsRationale: true });
  if (event.min_bidders && rows.length < event.min_bidders) out.push({ code: 'LIMITED_COMPETITION', detail: `${rows.length} valid bidder(s); the minimum is ${event.min_bidders}.`, needsRationale: true });
  const awarded = scenario.allocations.map((a) => by.get(a.supplier)).filter((r): r is CompareRow => !!r);
  const inc = awarded.filter((r) => r.tcoIncomplete);
  if (inc.length) out.push({ code: 'INCOMPLETE_TCO', detail: `Total cost has a missing input for ${inc.map((r) => `${r.supplier} (${r.tcoMissing.join(', ')})`).join(', ')}.`, needsRationale: false });
  const unv = awarded.filter((r) => !r.capacityVerified);
  if (unv.length) out.push({ code: 'UNVERIFIED_CAPACITY', detail: `Capacity is not verified for ${unv.map((r) => r.supplier).join(', ')}.`, needsRationale: false });
  if (scenario.annualSavingsMinor != null && scenario.annualSavingsMinor < 0) out.push({ code: 'NEGATIVE_SAVINGS', detail: `The award costs ${inr(Math.abs(scenario.annualSavingsMinor))} a year more than the baseline.`, needsRationale: true });
  return out;
}

/** Default minimum length of the override reason (SOURCING-POLICY.expiredOfferOverride.minReasonChars); the server's 409 carries the tenant's value. */
const OVERRIDE_MIN_CHARS = 20;

export function AwardDialog({ event, scenarios, comparison, initial, onClose, onNewRound }: { event: SourcingEvent; scenarios: Scenario[]; comparison?: Comparison; initial: string | null; onClose: () => void; onNewRound?: () => void }) {
  const path = `/sourcing/events/${encodeURIComponent(event.number)}`;
  const feasible = scenarios.filter((s) => s.feasible && !s.superseded);
  const [scenarioId, setScenarioId] = useState(initial ?? feasible[0]?.id ?? '');
  const [rationale, setRationale] = useState('');
  const [declaration, setDeclaration] = useState('');
  const [override, setOverride] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const scenario = feasible.find((s) => s.id === scenarioId);
  const exceptions = previewExceptions(event, scenario, comparison);
  const needs = exceptions.some((e) => e.needsRationale);
  const rows = comparison?.bids ?? [];
  const awardedRows = (scenario?.allocations ?? []).map((a) => rows.find((r) => r.supplier === a.supplier)).filter((r): r is CompareRow => !!r);
  const blocked = awardedRows.flatMap((r) => [
    ...(r.technicalGate && (!r.technicalGate.passed || r.technicalGate.pending.length) ? [`${r.supplier} has not passed the technical gate (${[...r.technicalGate.failed, ...r.technicalGate.pending].join(', ')})`] : []),
    ...((r.unscored?.length ?? 0) > 0 ? [`${r.supplier} is not scored on ${r.unscored!.join(', ')}`] : []),
  ]);
  // D5: an awarded offer whose validity has ended blocks the award (409 BID_OFFER_EXPIRED) unless a category manager of the event's category overrides it
  // with a written reason. The server's answer is authoritative: its list, minimum length and whether this user may override replace the preview.
  const serverExpired = error?.problem?.code === 'BID_OFFER_EXPIRED' ? (error.problem.expiredBids as ExpiredBid[] | undefined) ?? [] : null;
  const today = new Date().toISOString().slice(0, 10);
  const expired: ExpiredBid[] = serverExpired ?? awardedRows.filter((r) => r.validUntil && r.validUntil < today).map((r) => ({ supplier: r.supplier, validUntil: r.validUntil! }));
  const minChars = Number(error?.problem?.minReasonChars ?? OVERRIDE_MIN_CHARS);
  const roles = readSessionUser()?.roles ?? [];
  const mayOverride = error?.problem?.code === 'BID_OFFER_EXPIRED' ? error.problem.overrideAllowed === true : roles.includes('CATEGORY_MANAGER');
  const overrideOk = !expired.length || override.trim().length >= minChars;
  const ready = !!scenario && !!declaration.trim() && (!needs || !!rationale.trim()) && overrideOk;
  const award = useEventCommand(path, (_: void, ifMatch) => api.post(`${path}/award`, {
    scenario_id: scenarioId, rationale: rationale.trim() || undefined, conflict_declaration: declaration.trim(),
    expired_offer_override: expired.length && override.trim() ? override.trim() : undefined,
  }, ifMatchOptions(ifMatch)), { success: 'Award proposed – routed for approval where required', onSuccess: onClose, onError: setError, quiet: true });
  const serverExceptions = (error?.problem?.exceptions as AwardException[] | undefined) ?? [];
  return (
    <Dialog open title={`Propose award – ${event.number}`} onClose={onClose} wide>
      {!feasible.length ? <Empty title="No feasible scenario" hint="Build scenarios first; only current, feasible scenarios can be awarded." /> : (
        <div className="space-y-3">
          <Field label="Scenario">{(id) => (
            <Select id={id} value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}
              options={feasible.map((s) => ({ value: s.id, label: `${label(s.kind)} – ${s.allocations.map((a) => (a.lines ? `${a.supplier} ${a.lines.length} line(s)` : `${a.supplier} ${pct(a.share)}`)).join(' / ')} @ ${inr(s.weightedPriceMinor)}${event.lines.length > 1 ? ' a year' : ''}` }))} />
          )}</Field>
          {exceptions.length > 0 && (
            <div className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">
              <p className="font-semibold">This award carries {exceptions.length} exception(s); it always goes to the approvers</p>
              <ul className="mt-1 list-disc pl-5">{exceptions.map((e) => <li key={e.code}><span className="font-mono text-xs">{e.code}</span> {e.detail}{e.needsRationale ? ' A written rationale is required.' : ' Recorded; a rationale is needed when the policy says so.'}</li>)}</ul>
            </div>
          )}
          {blocked.length > 0 && (
            <div role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-900">
              <p className="font-semibold">The server will refuse this award</p>
              <ul className="mt-1 list-disc pl-5">{blocked.map((b) => <li key={b}>{b}</li>)}</ul>
            </div>
          )}
          {expired.length > 0 && (
            <div role="alert" aria-label="Expired offers" className="space-y-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
              <p className="font-semibold">Award blocked: an offer in this award has expired</p>
              <ul className="list-disc pl-5">{expired.map((b) => (
                <li key={b.supplier}>{b.supplierName ? `${b.supplierName} (${b.supplier})` : b.supplier}: offer valid until {b.validUntil}{b.daysExpired ? ` – expired ${b.daysExpired} day(s) ago` : ''}</li>
              ))}</ul>
              <p>The safe way: start a new round so the supplier confirms or extends its offer, then award on the new bid.</p>
              {onNewRound && <Button onClick={onNewRound}>Start a new round instead</Button>}
              {mayOverride ? (
                <Field label={`Override reason (at least ${minChars} characters)`} hint="Only a category manager of this category may override. The reason is recorded on the award decision and in the audit trail, and the award goes to the approvers.">{(id) => (
                  <Textarea id={id} value={override} maxLength={2000} onChange={(e) => setOverride(e.target.value)} placeholder="e.g. The supplier confirmed the price in writing (letter reference, date) until …" />
                )}</Field>
              ) : <p className="text-xs">You cannot override this block: ask a category manager of {event.category}, or start a new round.</p>}
            </div>
          )}
          <Field label={`Rationale${needs ? ' (required)' : ' (optional)'}`} hint="At least the minimum length set by SOURCING-POLICY (default 15 characters). Say why: capacity, risk, quality, TCO.">{(id) => <Textarea id={id} value={rationale} onChange={(e) => setRationale(e.target.value)} placeholder="Why this allocation – capacity, risk, quality, TCO…" />}</Field>
          <Field label="Conflict-of-interest declaration (required)" hint="Recorded with your name on the award decision (SRC-05).">{(id) => (
            <Textarea id={id} value={declaration} onChange={(e) => setDeclaration(e.target.value)} placeholder="I have no personal or financial interest in any bidder." />
          )}</Field>
          <ProblemBox error={error} />
          {serverExceptions.length > 0 && (
            <ul className="list-disc rounded-lg bg-slate-50 p-2 pl-6 text-sm" aria-label="Exceptions reported by the server">{serverExceptions.map((e) => <li key={e.code}><span className="font-mono text-xs">{e.code}</span> {e.detail}</li>)}</ul>
          )}
          <p className="text-xs text-slate-500">The authority band (approval chain by annual value) is stored on the decision. Awards above the approval threshold, to a non-lowest bid or with the exceptions above go to the approvers; they decide from the task panel on this page.</p>
        </div>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!ready} busy={award.isPending} onClick={() => { setError(null); award.mutate(); }}>Propose award</Button>
      </div>
    </Dialog>
  );
}

/** States from which POST …/cancel is allowed (sourcing.SM: anything before the award). */
export const CANCELLABLE = ['DRAFT', 'PUBLISHED', 'OPEN', 'CLOSED', 'UNDER_EVALUATION', 'AWARD_PENDING'];

export function CancelEventDialog({ event, onClose }: { event: SourcingEvent; onClose: () => void }) {
  const path = `/sourcing/events/${encodeURIComponent(event.number)}`;
  const [reason, setReason] = useState('');
  const cancel = useEventCommand(path, (_: void, ifMatch) => api.post(`${path}/cancel`, { reason: reason.trim() }, ifMatchOptions(ifMatch)), {
    success: `${event.number} cancelled${event.status !== 'DRAFT' ? ' – invited suppliers are notified' : ''}`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`Cancel ${event.number}`} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-slate-700">
          The event stops here: open approval tasks and timers close{event.status === 'AWARD_PENDING' ? ', the pending award decision is withdrawn' : ''},
          requirement lines no other event is sourcing go back to open, and the savings initiative is marked lost.
          {event.status !== 'DRAFT' ? ' Every invited supplier is told the event was cancelled and why.' : ''} This cannot be undone.
        </p>
        <Field label="Reason (required, shown to invited suppliers)">{(id) => (
          <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Requirement withdrawn after the design change ECN-2240" />
        )}</Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Keep event</Button>
        <Button variant="danger" disabled={!reason.trim()} busy={cancel.isPending} onClick={() => cancel.mutate()}>Cancel event</Button>
      </div>
    </Dialog>
  );
}

