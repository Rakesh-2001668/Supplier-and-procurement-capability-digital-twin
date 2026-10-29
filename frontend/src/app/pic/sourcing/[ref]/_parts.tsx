'use client';

import { Lock } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Button, DataTable, Dialog, Empty, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { dateTime, inr, label, qty } from '@/lib/pic/format';
import { useCommand } from '@/lib/pic/hooks';

// ---------------------------------------------------------------- shapes (GET /sourcing/events/{ref}, GET …/bids, POST …/scenarios)
export type EventLine = { id: string; line_no: number; description: string; plant: string; annual_qty: string; monthly_qty: string; uom: string;
  requisition_id: string | null; pr_line_no: number | null };
export type Criterion = { id: string; code: string; name: string; weight: number };
export type Invitee = { id: string; code: string; name: string; categoryStatus: string; waiver: string | null };
export type BidMeta = { supplier: string; round: number; status: string; submittedAt: string; hash: string };
export type ScenarioRaw = Record<string, unknown> & { id: string; kind: string; feasible: boolean; allocations: Allocation[]; explanation: Record<string, unknown> | null };
export type Allocation = { supplier: string; supplierId: string; share: string; monthlyQty: string; annualQty: string; priceMinor: number; tcoMinor: number };
export type Scenario = { id: string; kind: string; feasible: boolean; allocations: Allocation[]; weightedPriceMinor: number | null;
  weightedTcoMinor: number | null; annualSavingsMinor: number | null; explanation: Record<string, unknown> | null };
export type AwardDecision = { id: string; scenario_id: string; status: string; rationale: string | null; conflict_declarations: { user: string; declaration: string }[];
  annual_value_minor: number; rule_set_version: string; created_at: string };
export type ShouldCost = { model: string; material: string; conversion: string; tooling: string; packaging: string; subtotal: string;
  overheadMarginPct: string; unitCost: string; unitCostMinor: number };
export type SourcingEvent = {
  id: string; number: string; type: string; title: string; category: string; status: string; round: number; weights_locked: boolean; owner_id?: string;
  published_at: string | null; close_at: string; closed_at: string | null; unsealed_at: string | null; baseline_price_minor: number | null;
  baseline_method: string | null; should_cost: ShouldCost | null; constraints: { max_suppliers?: number; max_share?: string; min_share?: string } | null;
  tco_params: Record<string, string | number> | null; savings_target_pct: string | null;
  auction?: Record<string, unknown> | null; auction_ends_at?: string | null;
  lines: EventLine[]; criteria: Criterion[]; invitees: Invitee[]; bids: BidMeta[]; scenarios: ScenarioRaw[]; awardDecisions: AwardDecision[];
};
export type MatrixRow = { supplier: string; supplierId: string; round: number; bidId: string; priceMinor: number; tcoMinor: number;
  tco: Record<string, number>; leadTimeDays: number; paymentTermsDays: number; verifiedCapacityPerMonth: string | null;
  lateDeliveryProb: string | null; shouldCostDeltaMinor: number | null; scores?: Record<string, string>; weightedScore?: string };

/** Persisted scenarios come back snake_case on the event, fresh ones camelCase from POST …/scenarios. */
export function normaliseScenario(s: ScenarioRaw): Scenario {
  const pick = (a: string, b: string) => (s[a] ?? s[b] ?? null) as number | null;
  return { id: s.id, kind: s.kind, feasible: s.feasible, allocations: s.allocations ?? [], explanation: s.explanation,
    weightedPriceMinor: pick('weightedPriceMinor', 'weighted_price_minor'), weightedTcoMinor: pick('weightedTcoMinor', 'weighted_tco_minor'),
    annualSavingsMinor: pick('annualSavingsMinor', 'annual_savings_minor') };
}

export function toLocalInput(d: Date) {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

const pct = (v: string | number | null | undefined, digits = 0) => (v === null || v === undefined || v === '' ? '–' : `${(Number(v) * 100).toFixed(digits)}%`);
const TCO_PARTS: [string, string][] = [['price', 'Price'], ['freight', 'Freight'], ['duty', 'Duty'], ['packaging', 'Packaging'],
  ['carrying', 'Inventory carrying (lead time)'], ['quality', 'Quality cost (PPM × CoPQ)'], ['paymentTermValue', 'Payment-term value']];

// ---------------------------------------------------------------- bids: sealed metadata + evaluation matrix
export function BidsPanel({ event, sealed, requested, onRequest, matrix, loading, error }: {
  event: SourcingEvent; sealed: boolean; requested: boolean; onRequest: () => void; matrix?: MatrixRow[]; loading: boolean; error: ApiError | null;
}) {
  const manual = event.criteria.filter((c) => c.code !== 'PRICE_TCO');
  const bestScore = matrix?.length ? Math.max(...matrix.map((m) => Number(m.weightedScore ?? 0))) : null;
  return (
    <div className="space-y-5">
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Bid receipts (metadata only)</h3>
        <DataTable<BidMeta & Record<string, unknown>> rows={event.bids.map((b) => ({ ...b, id: `${b.supplier}-${b.round}` }))} empty="No bids received yet"
          columns={[
            { key: 'supplier', header: 'Supplier' },
            { key: 'round', header: 'Round', align: 'right' },
            { key: 'status', header: 'Status', render: (b) => <StatusChip status={b.status as string} /> },
            { key: 'submittedAt', header: 'Submitted', render: (b) => dateTime(b.submittedAt as string) },
            { key: 'hash', header: 'Sealed payload hash (SHA-256)', render: (b) => <span className="font-mono text-[11px] text-slate-500" title={b.hash as string}>{(b.hash as string).slice(0, 16)}…</span> },
          ]} />
        <p className="mt-1 text-xs text-slate-500">Prices are never shown here. The hash proves the bid content was not changed between submission and unsealing.</p>
      </div>

      <div>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evaluation matrix</h3>
          {!requested && <Button onClick={onRequest}>View bids</Button>}
        </div>
        {!requested ? (
          <p className="text-sm text-slate-600">{sealed ? `Bids are sealed until ${dateTime(event.close_at)}. Any attempt to open them before close is blocked and written to the audit trail.` : 'Load the TCO evaluation matrix of the unsealed bids.'}</p>
        ) : loading ? <Loading /> : error ? (error.status === 423 ? <SealedLock error={error} closeAt={event.close_at} /> : <ProblemBox error={error} />) : !matrix?.length ? (
          <Empty title="No unsealed bids" hint="No supplier submitted a bid in this round." />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left">Supplier</th>
                  <th scope="col" className="px-3 py-2 text-right">Price</th>
                  <th scope="col" className="px-3 py-2 text-right">TCO / unit</th>
                  <th scope="col" className="px-3 py-2 text-right">Lead time</th>
                  <th scope="col" className="px-3 py-2 text-right">Terms</th>
                  <th scope="col" className="px-3 py-2 text-right">Verified capacity / month</th>
                  <th scope="col" className="px-3 py-2 text-right">Late prob.</th>
                  <th scope="col" className="px-3 py-2 text-right">vs should-cost</th>
                  {['PRICE_TCO', ...manual.map((c) => c.code)].map((c) => <th key={c} scope="col" className="px-3 py-2 text-right">{c.replace(/_/g, ' ')}</th>)}
                  <th scope="col" className="px-3 py-2 text-right">Weighted</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {matrix.map((m, i) => (
                  <tr key={m.bidId} className="align-top">
                    <td className="px-3 py-2">
                      <Link href={`/pic/suppliers/${encodeURIComponent(m.supplier)}`} className="font-medium text-[#1A56DB] hover:underline">{m.supplier}</Link>
                      <span className="ml-1 text-xs text-slate-500">round {m.round}</span>
                      <div className="mt-0.5 flex flex-wrap gap-1">
                        {i === 0 && <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-emerald-800">Lowest TCO</span>}
                        {bestScore !== null && Number(m.weightedScore ?? 0) === bestScore && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-blue-800">Best score</span>}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{inr(m.priceMinor)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      <details>
                        <summary className="cursor-pointer font-semibold">{inr(m.tcoMinor)}</summary>
                        <dl className="mt-1 space-y-0.5 text-left text-xs text-slate-600">
                          {TCO_PARTS.filter(([k]) => m.tco?.[k] !== undefined).map(([k, name]) => (
                            <div key={k} className="flex justify-between gap-3"><dt>{name}</dt><dd className="tabular-nums">{inr(m.tco[k])}</dd></div>
                          ))}
                        </dl>
                      </details>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{m.leadTimeDays} d</td>
                    <td className="px-3 py-2 text-right tabular-nums">{m.paymentTermsDays} d</td>
                    <td className="px-3 py-2 text-right tabular-nums">{qty(m.verifiedCapacityPerMonth)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{pct(m.lateDeliveryProb)}</td>
                    <td className={`px-3 py-2 text-right tabular-nums ${m.shouldCostDeltaMinor && m.shouldCostDeltaMinor > 0 ? 'text-amber-700' : 'text-emerald-700'}`}>
                      {m.shouldCostDeltaMinor === null ? '–' : `${m.shouldCostDeltaMinor > 0 ? '+' : ''}${inr(m.shouldCostDeltaMinor)}`}
                    </td>
                    {['PRICE_TCO', ...manual.map((c) => c.code)].map((c) => <td key={c} className="px-3 py-2 text-right tabular-nums">{m.scores?.[c] ?? '–'}</td>)}
                    <td className="px-3 py-2 text-right font-semibold tabular-nums">{m.weightedScore ?? '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="border-t border-slate-100 px-3 py-2 text-xs text-slate-500">
              TCO = price + freight + duty + packaging + carrying cost of lead time + quality cost (twin PPM) − value of payment terms. Capacity is the lower of the offer and the digital twin&apos;s verified free capacity.
              Criterion scores are averages across evaluators; PRICE_TCO = best TCO ÷ this TCO × 100.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function SealedLock({ error, closeAt }: { error: ApiError; closeAt: string }) {
  return (
    <div role="alert" className="flex gap-3 rounded-lg border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-800">
      <Lock className="mt-0.5 h-5 w-5 shrink-0 text-slate-600" aria-hidden />
      <div>
        <p className="font-semibold">Bids are sealed</p>
        <p className="mt-0.5">{error.problem.detail ?? `Bids stay sealed until ${dateTime(closeAt)}.`}</p>
        <p className="mt-1 text-xs text-slate-600">
          Sealed bidding keeps every supplier&apos;s price confidential until the close time, so nobody can steer the result. This access attempt has been logged in the audit trail
          {error.problem.ruleRef ? ` (rule ${error.problem.ruleRef})` : ''}. The matrix opens automatically once the event is closed.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- award scenarios side by side
export function ScenariosPanel({ event, scenarios, canAward, onAward }: { event: SourcingEvent; scenarios: Scenario[]; canAward: boolean; onAward: (id: string) => void }) {
  const line = event.lines[0];
  return (
    <div className="space-y-5">
      {!scenarios.length ? (
        <Empty title="No award scenarios yet" hint="After close, build scenarios to compare lowest cost, best value and the capacity-constrained optimum." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          {scenarios.map((s) => {
            const decision = event.awardDecisions.find((d) => d.scenario_id === s.id);
            return (
              <article key={s.id} className={`flex flex-col rounded-xl border p-4 ${s.feasible ? 'border-slate-200' : 'border-red-200 bg-red-50/30'}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold">{label(s.kind)}</h3>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ring-1 ring-inset ${s.feasible ? 'bg-emerald-50 text-emerald-800 ring-emerald-200' : 'bg-red-50 text-red-800 ring-red-200'}`}>
                    {s.feasible ? 'Feasible' : 'Infeasible'}
                  </span>
                </div>
                <table className="mt-3 w-full text-sm">
                  <thead className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                    <tr><th className="py-1">Supplier</th><th className="py-1 text-right">Share</th><th className="py-1 text-right">Qty / month</th><th className="py-1 text-right">Price</th></tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {s.allocations.length ? s.allocations.map((a) => (
                      <tr key={a.supplier}>
                        <td className="py-1 font-medium">{a.supplier}</td>
                        <td className="py-1 text-right tabular-nums">{pct(a.share)}</td>
                        <td className="py-1 text-right tabular-nums" title={`${qty(a.annualQty)} per year`}>{qty(a.monthlyQty)}</td>
                        <td className="py-1 text-right tabular-nums">{inr(a.priceMinor)}</td>
                      </tr>
                    )) : <tr><td colSpan={4} className="py-2 text-slate-500">No allocation possible</td></tr>}
                  </tbody>
                </table>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
                  <div><dt className="text-xs text-slate-500">Weighted price</dt><dd className="font-semibold tabular-nums">{inr(s.weightedPriceMinor)}</dd></div>
                  <div><dt className="text-xs text-slate-500">Weighted TCO</dt><dd className="font-semibold tabular-nums">{inr(s.weightedTcoMinor)}</dd></div>
                  <div className="col-span-2"><dt className="text-xs text-slate-500">Annual savings vs baseline {event.baseline_price_minor ? inr(event.baseline_price_minor) : ''}{line ? ` × ${qty(line.annual_qty, line.uom)}` : ''}</dt>
                    <dd className={`font-semibold tabular-nums ${s.annualSavingsMinor && s.annualSavingsMinor > 0 ? 'text-emerald-700' : ''}`}>{inr(s.annualSavingsMinor)}</dd></div>
                </dl>
                {s.explanation && <Explanation e={s.explanation} />}
                <div className="mt-auto pt-3">
                  {decision && <p className="mb-2 flex items-center gap-2 text-xs">Award decision <StatusChip status={decision.status} /></p>}
                  {canAward && s.feasible && <Button variant="primary" className="w-full" onClick={() => onAward(s.id)}>Award this scenario</Button>}
                </div>
              </article>
            );
          })}
        </div>
      )}
      {event.awardDecisions.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Award decisions</h3>
          <ul className="space-y-2">
            {event.awardDecisions.map((d) => (
              <li key={d.id} className="rounded-lg border border-slate-200 p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusChip status={d.status} />
                  <span className="font-medium">{label(scenarios.find((s) => s.id === d.scenario_id)?.kind ?? 'scenario')}</span>
                  <span className="text-slate-600">· annual value {inr(d.annual_value_minor)} · {dateTime(d.created_at)}</span>
                  <span className="font-mono text-[11px] text-slate-400">{d.rule_set_version}</span>
                </div>
                {d.rationale && <p className="mt-1 text-slate-700">Rationale: {d.rationale}</p>}
                {d.conflict_declarations?.map((c) => <p key={c.user} className="mt-0.5 text-xs text-slate-500">Conflict declaration by {c.user}: “{c.declaration}”</p>)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Explanation({ e }: { e: Record<string, unknown> }) {
  const bounds = e.bounds as Record<string, string> | undefined;
  return (
    <div className="mt-3 rounded-lg bg-slate-50 p-2 text-xs text-slate-600">
      {typeof e.rule === 'string' && <p><span className="font-semibold">Rule:</span> {e.rule}</p>}
      {typeof e.capacityCheck === 'string' && <p><span className="font-semibold">Capacity:</span> {e.capacityCheck}</p>}
      {typeof e.Q === 'string' && <p><span className="font-semibold">Demand Q:</span> {qty(e.Q)} / month</p>}
      {bounds && <ul className="mt-1 font-mono text-[11px]">{Object.entries(bounds).map(([k, v]) => <li key={k}>{k}: {v}</li>)}</ul>}
    </div>
  );
}

// ---------------------------------------------------------------- dialogs
export function ScoreDialog({ event, matrix, onClose }: { event: SourcingEvent; matrix: MatrixRow[]; onClose: () => void }) {
  const manual = event.criteria.filter((c) => c.code !== 'PRICE_TCO');
  const [scores, setScores] = useState<Record<string, string>>({});
  const [comments, setComments] = useState<Record<string, string>>({});
  const entries = matrix.flatMap((m) => manual.filter((c) => (scores[`${m.supplier}|${c.code}`] ?? '') !== '').map((c) => ({
    supplier: m.supplier, criterion: c.code, score: Number(scores[`${m.supplier}|${c.code}`]), comment: comments[m.supplier] || undefined,
  })));
  const invalid = entries.some((e) => Number.isNaN(e.score) || e.score < 0 || e.score > 100);
  const save = useCommand(() => api.post(`/sourcing/events/${encodeURIComponent(event.number)}/scores`, entries),
    { success: `${entries.length} score(s) recorded`, onSuccess: onClose });
  return (
    <Dialog open title={`Score bids – ${event.number}`} onClose={onClose}>
      {!manual.length ? <Empty title="No manually scored criteria" hint="This event is scored on price/TCO only." /> : (
        <>
          <p className="mb-3 text-sm text-slate-600">Enter your own evaluation (0–100) per criterion. Price/TCO is computed from the bids and is not scored by hand. Leave a cell empty to skip it.</p>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                <tr><th className="py-1 pr-2">Supplier</th>{manual.map((c) => <th key={c.code} className="py-1 pr-2">{c.name} <span className="normal-case text-slate-400">({c.weight}%)</span></th>)}<th className="py-1">Comment</th></tr>
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
  const [closeAt, setCloseAt] = useState(() => toLocalInput(new Date(Date.now() + 3 * 864e5)));
  const [note, setNote] = useState('');
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);
  const when = new Date(closeAt);
  const future = !Number.isNaN(when.getTime()) && when.getTime() > now;
  const go = useCommand(() => api.post(`/sourcing/events/${encodeURIComponent(event.number)}/rounds`, { close_at: when.toISOString(), note }),
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

export function AwardDialog({ event, scenarios, matrix, initial, onClose }: { event: SourcingEvent; scenarios: Scenario[]; matrix?: MatrixRow[]; initial: string | null; onClose: () => void }) {
  const feasible = scenarios.filter((s) => s.feasible);
  const [scenarioId, setScenarioId] = useState(initial ?? feasible[0]?.id ?? '');
  const [rationale, setRationale] = useState('');
  const [declaration, setDeclaration] = useState('');
  const scenario = feasible.find((s) => s.id === scenarioId);
  const lowest = matrix?.length ? Math.min(...matrix.map((m) => m.priceMinor)) : null;
  // Without the matrix we cannot prove the award goes to the lowest bid, so ask for a rationale.
  const notLowest = !scenario || lowest === null || scenario.allocations.some((a) => a.priceMinor > lowest);
  const ready = !!scenario && !!declaration.trim() && (!notLowest || !!rationale.trim());
  const award = useCommand(() => api.post(`/sourcing/events/${encodeURIComponent(event.number)}/award`,
    { scenario_id: scenarioId, rationale: rationale.trim() || undefined, conflict_declaration: declaration.trim() }),
  { success: 'Award proposed – routed for approval where required', onSuccess: onClose });
  return (
    <Dialog open title={`Propose award – ${event.number}`} onClose={onClose}>
      {!feasible.length ? <Empty title="No feasible scenario" hint="Build scenarios first; only feasible scenarios can be awarded." /> : (
        <div className="space-y-3">
          <Field label="Scenario">{(id) => (
            <Select id={id} value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}
              options={feasible.map((s) => ({ value: s.id, label: `${label(s.kind)} – ${s.allocations.map((a) => `${a.supplier} ${pct(a.share)}`).join(' / ')} @ ${inr(s.weightedPriceMinor)}` }))} />
          )}</Field>
          {scenario && notLowest && (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {lowest === null ? 'The bid matrix is not loaded, so a written rationale is required.' : `This scenario awards volume above the lowest bid (${inr(lowest)}). A written rationale is required (SRC-RATIONALE) and the award goes to approval.`}
            </p>
          )}
          <Field label={`Rationale${notLowest ? ' (required)' : ' (optional)'}`}>{(id) => <Textarea id={id} value={rationale} onChange={(e) => setRationale(e.target.value)} placeholder="Why this allocation – capacity, risk, quality, TCO…" />}</Field>
          <Field label="Conflict-of-interest declaration (required)" hint="Recorded with your name on the award decision (SRC-05).">{(id) => (
            <Textarea id={id} value={declaration} onChange={(e) => setDeclaration(e.target.value)} placeholder="I have no personal or financial interest in any bidder." />
          )}</Field>
          <p className="text-xs text-slate-500">Awards above the approval threshold or not to the lowest bid go to the approvers in the award approval band; they decide from the task panel on this page.</p>
        </div>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!ready} busy={award.isPending} onClick={() => award.mutate()}>Propose award</Button>
      </div>
    </Dialog>
  );
}

/** States from which POST …/cancel is allowed (sourcing.SM: anything before the award). */
export const CANCELLABLE = ['DRAFT', 'PUBLISHED', 'OPEN', 'CLOSED', 'UNDER_EVALUATION', 'AWARD_PENDING'];

export function CancelEventDialog({ event, onClose }: { event: SourcingEvent; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const cancel = useCommand(() => api.post(`/sourcing/events/${encodeURIComponent(event.number)}/cancel`, { reason: reason.trim() }), {
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
