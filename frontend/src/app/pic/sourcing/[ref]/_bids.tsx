'use client';

// Bids and opening ceremony, evaluation (conflict declarations, scoring, technical gate, disqualification) and the comparison matrix.
import { Lock } from 'lucide-react';
import Link from 'next/link';
import { Fragment, useState } from 'react';
import { Button, Card, Dialog, Empty, Field, Kpi, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api, ApiError, readSessionUser } from '@/lib/pic/api';
import { date, dateTime, inr, label, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { CompareRow, Comparison, CsvDownload, fetchCsv, FLAG_TEXT, ifMatchOptions, saveFile, useEventCommand } from '../_lib';
import { TcoStack, TraceTable } from '../_tco';
import type { BidMeta, SourcingEvent } from './_parts';

type Evaluator = { user: string; hasConflict: boolean; declaration: string; declaredAt: string; scores: number };
type HistoryEntry = { seq: number; at: string; actor: string | null; action: string; reason: string | null; ruleSet: string | null; before: Record<string, unknown> | null; after: Record<string, unknown> | null; hash: string };

const SEALED_EVIDENCE = ['BIDS_UNSEALED', 'BIDS_OPEN_WITNESS', 'AWAITING_OPENING', 'BID_ACCESS_DENIED', 'LATE_BID_REFUSED', 'UNINVITED_BID_REFUSED', 'INELIGIBLE_BID_REFUSED',
  'DISQUALIFIED_BID_REFUSED', 'BID_WITHDRAWN', 'BID_REPLACED', 'BID_DISQUALIFIED', 'BID_INVALID', 'COMPARISON_EXPORTED'];
const pctOf = (v: string | number | null | undefined) => (v === null || v === undefined || v === '' ? '–' : `${(Number(v) * 100).toFixed(0)}%`);

export function SealedLock({ error, closeAt }: { error: ApiError; closeAt: string }) {
  return (
    <div role="alert" className="flex gap-3 rounded-lg border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-800">
      <Lock className="mt-0.5 h-5 w-5 shrink-0 text-slate-600" aria-hidden />
      <div>
        <p className="font-semibold">Bids are sealed (HTTP {error.status} {error.problem.code})</p>
        <p className="mt-0.5">{error.problem.detail ?? `Bids stay sealed until ${dateTime(closeAt)}.`}</p>
        <p className="mt-1 text-xs text-slate-600">
          Sealed bidding keeps every supplier&apos;s price confidential until the opening, so nobody can steer the result. This attempt was written to the audit trail as BID_ACCESS_DENIED
          {error.problem.ruleRef ? ` (rule ${error.problem.ruleRef})` : ''}; it appears under Evidence and in the History tab.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- bids and opening
export function BidsOpeningPanel({ event, path, canManage }: { event: SourcingEvent; path: string; canManage: boolean }) {
  const me = readSessionUser();
  const [attempt, setAttempt] = useState<ApiError | null>(null);
  const history = useApi<HistoryEntry[]>(canManage && event.status !== 'DRAFT' ? `${path}/history` : null);
  const peek = async () => {
    try {
      await api.get(`${path}/bids`);
      setAttempt(null);
    } catch (e) {
      setAttempt(e as ApiError);
    }
    history.refetch();
  };
  const openers = event.opening?.openers ?? [];
  const required = !!event.opening?.required;
  const iOpened = !!me && openers.includes(me.id);
  const open = useEventCommand(path, (_: void, ifMatch) => api.post<{ unsealed: number; openers?: number; remaining?: number; awaitingOpening?: boolean }>(`${path}/open`, {}, ifMatchOptions(ifMatch)), {
    success: (r) => (r.awaitingOpening ? `Opening recorded (${r.openers} of 2): ${r.remaining} more person needed` : `Bids opened: ${r.unsealed} bid(s) unsealed and evaluated`),
  });
  const evidence = (history.data ?? []).filter((h) => SEALED_EVIDENCE.includes(h.action));
  const sealed = ['DRAFT', 'PUBLISHED', 'OPEN'].includes(event.status) || !event.unsealed_at;
  return (
    <div className="space-y-5">
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Bid receipts (metadata only)</h3>
        <ReceiptTable bids={event.bids} />
        <p className="mt-1 text-xs text-slate-500">Prices are never shown here. The hash proves the sealed content was not changed between submission and opening.</p>
      </div>

      <div className="rounded-lg border border-slate-200 p-4">
        <h3 className="text-sm font-semibold">Opening</h3>
        {event.status === 'CLOSED' && required ? (
          <div className="mt-2 space-y-3">
            <p className="text-sm text-slate-700" role="status">
              Two-person opening for round {event.opening?.round ?? event.round}: <span className="font-semibold">{openers.length} of 2</span> openers have witnessed it. The bids stay sealed
              until two different people have opened them{iOpened ? '; you have already opened them, a second person must do the same' : ''}.
            </p>
            {canManage && (
              <Button variant="primary" busy={open.isPending} disabled={iOpened} onClick={() => open.mutate()}
                title={iOpened ? 'ALREADY_OPENED_BY_YOU: a second, different person must open' : undefined}>
                {openers.length ? 'Open bids as the second opener' : 'Open bids (first opener)'}
              </Button>
            )}
          </div>
        ) : event.status === 'CLOSED' ? (
          <p className="mt-2 text-sm text-slate-700">The event is closed and the bids are being opened.</p>
        ) : event.unsealed_at ? (
          <p className="mt-2 text-sm text-slate-700" role="status">
            Bids of round {event.round} unsealed {dateTime(event.unsealed_at)}{required ? ` after a two-person opening (${openers.length} openers)` : ' when the close time was reached'}.
            {event.competitive != null && <> The event is <span className="font-semibold">{event.competitive ? 'competitive' : 'not competitive'}</span> ({event.min_bidders ?? '–'} bidders required).</>}
          </p>
        ) : (
          <p className="mt-2 text-sm text-slate-700">
            Bids are sealed until {dateTime(event.close_at)}{event.opening?.required || (event.constraints as Record<string, unknown> | null)?.two_person_opening ? ' and are then opened by two people' : ''}.
            An attempt to read them before the opening is blocked and written to the audit trail.
          </p>
        )}
        {sealed && canManage && event.status !== 'DRAFT' && (
          <div className="mt-3 space-y-2">
            <Button onClick={peek}>Try to read the bids now</Button>
            {attempt && (attempt.status === 423 ? <SealedLock error={attempt} closeAt={event.close_at} /> : <ProblemBox error={attempt} />)}
          </div>
        )}
      </div>

      {canManage && event.status !== 'DRAFT' && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence (audit trail of the sealed bids)</h3>
          {history.isLoading ? <Loading /> : history.error ? <ProblemBox error={history.error} /> : !evidence.length ? (
            <p className="text-sm text-slate-500">No sealed-bid events recorded yet.</p>
          ) : (
            <ol className="space-y-1 text-sm" aria-label="Sealed bid evidence">
              {evidence.map((h) => (
                <li key={h.seq} className="flex flex-wrap items-baseline gap-x-3 border-b border-slate-100 py-1">
                  <span className="w-40 text-xs text-slate-500">{dateTime(h.at)}</span>
                  <span className="font-mono text-xs font-semibold">{h.action}</span>
                  <span className="text-slate-600">{h.actor ?? 'system'}</span>
                  {h.reason && <span className="text-slate-500">{h.reason}</span>}
                  {h.action === 'BIDS_UNSEALED' && h.after && <span className="text-xs text-slate-500">round {String(h.after.round)} · {String(h.after.bids)} bid(s) · event sourcing.bids.unsealed</span>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}

function ReceiptTable({ bids }: { bids: BidMeta[] }) {
  if (!bids.length) return <Empty title="No bids received yet" />;
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <caption className="sr-only">Bid receipts</caption>
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr><th scope="col" className="px-3 py-2 text-left">Supplier</th><th scope="col" className="px-3 py-2 text-right">Round</th><th scope="col" className="px-3 py-2 text-left">Status</th>
            <th scope="col" className="px-3 py-2 text-left">Submitted</th><th scope="col" className="px-3 py-2 text-left">Sealed payload hash (SHA-256)</th></tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {bids.map((b) => (
            <tr key={`${b.supplier}-${b.round}`}>
              <td className="px-3 py-2">{b.supplier}</td><td className="px-3 py-2 text-right">{b.round}</td><td className="px-3 py-2"><StatusChip status={b.status} /></td>
              <td className="px-3 py-2">{dateTime(b.submittedAt)}</td>
              <td className="px-3 py-2 font-mono text-[11px] text-slate-500" title={b.hash}>{b.hash.slice(0, 16)}…</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- evaluation: declarations, scores, technical gate, disqualification
export function EvaluationPanel({ event, path, canManage, canScore, comparison, onScore }: {
  event: SourcingEvent; path: string; canManage: boolean; canScore: boolean; comparison?: Comparison; onScore: () => void;
}) {
  const evaluators = useApi<Evaluator[]>(canManage ? `${path}/evaluators` : null);
  const [dialog, setDialog] = useState<'declare' | 'disqualify' | null>(null);
  const me = readSessionUser();
  const mine = evaluators.data?.find((e) => e.user === me?.email);
  const evaluating = event.status === 'UNDER_EVALUATION';
  const gated = event.criteria.filter((c) => c.min_score != null);
  const rows = comparison?.bids ?? [];
  const noConflict = (evaluators.data ?? []).filter((e) => !e.hasConflict).length;
  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-600">
        Every evaluator declares a conflict of interest before scoring; a declared conflict bars the person from scoring and from proposing the award. Scores are 0 to 100 per manual criterion
        and averaged across evaluators. {gated.length ? 'A criterion with a minimum score is a technical gate: a bidder below it, or not scored yet, cannot be awarded.' : ''}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {(canScore || canManage) && evaluating && <Button onClick={() => setDialog('declare')}>{mine ? 'My declaration' : 'Declare conflict of interest'}</Button>}
        {canScore && evaluating && <Button variant="primary" onClick={onScore} disabled={!rows.length || (canManage && !mine)}
          title={canManage && !mine ? 'Declare your conflict of interest first (required before scoring)' : undefined}>Score bids</Button>}
        {canManage && evaluating && <Button variant="danger" onClick={() => setDialog('disqualify')} disabled={!rows.length}>Disqualify a bidder</Button>}
      </div>

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Evaluators and declarations</h3>
        {!canManage ? <p className="text-sm text-slate-500">The evaluation team overview is shown to users who manage sourcing events.</p>
          : evaluators.isLoading ? <Loading /> : evaluators.error ? <ProblemBox error={evaluators.error} /> : !evaluators.data?.length ? (
            <Empty title="No declarations yet" hint="Nobody can score before declaring." />
          ) : (
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <caption className="sr-only">Conflict-of-interest declarations and scores entered per evaluator</caption>
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr>
                  <th scope="col" className="px-3 py-2 text-left">Evaluator</th><th scope="col" className="px-3 py-2 text-left">Conflict</th><th scope="col" className="px-3 py-2 text-left">Declaration</th>
                  <th scope="col" className="px-3 py-2 text-left">Declared</th><th scope="col" className="px-3 py-2 text-right">Scores entered</th></tr></thead>
                <tbody className="divide-y divide-slate-100 bg-white align-top">
                  {evaluators.data.map((e) => (
                    <tr key={e.user}>
                      <td className="px-3 py-2">{e.user}</td>
                      <td className="px-3 py-2"><StatusChip status={e.hasConflict ? 'CONFLICT' : 'OK'} /> <span className="sr-only">{e.hasConflict ? 'conflict declared' : 'no conflict'}</span></td>
                      <td className="px-3 py-2 text-slate-700">{e.declaration}</td><td className="px-3 py-2">{dateTime(e.declaredAt)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{e.scores}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="border-t border-slate-100 px-3 py-2 text-xs text-slate-500">{noConflict} evaluator(s) without conflict. The sole evaluator of an event cannot award it (SOD-05).</p>
            </div>
          )}
      </div>

      {gated.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Technical gate</h3>
          <ul className="space-y-1 text-sm">
            {gated.map((c) => <li key={c.code}>{c.name} ({c.code}) minimum <span className="font-semibold tabular-nums">{String(c.min_score)}</span></li>)}
          </ul>
          {rows.length > 0 && (
            <ul className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3" aria-label="Technical gate by bidder">
              {rows.map((r) => (
                <li key={r.bidId} className="rounded-lg border border-slate-200 p-2 text-sm">
                  <span className="font-medium">{r.supplier}</span>{' '}
                  <GateChip row={r} />
                  {r.technicalGate && !r.technicalGate.passed && <p className="text-xs text-red-700">below the minimum on {r.technicalGate.failed.join(', ')}</p>}
                  {r.technicalGate && r.technicalGate.pending.length > 0 && <p className="text-xs text-amber-800">not scored yet on {r.technicalGate.pending.join(', ')}</p>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {dialog === 'declare' && <DeclarationDialog path={path} existing={mine} onClose={() => setDialog(null)} />}
      {dialog === 'disqualify' && <DisqualifyDialog path={path} rows={rows} onClose={() => setDialog(null)} />}
    </div>
  );
}

function GateChip({ row }: { row: CompareRow }) {
  const g = row.technicalGate;
  if (!g || !Object.keys(g.thresholds).length) return <span className="text-xs text-slate-500">no gate</span>;
  return <StatusChip status={g.passed && !g.pending.length ? 'PASSED' : g.passed ? 'PENDING' : 'FAILED'} />;
}

function DeclarationDialog({ path, existing, onClose }: { path: string; existing?: Evaluator; onClose: () => void }) {
  const [conflict, setConflict] = useState(false);
  const [text, setText] = useState('');
  const declare = useEventCommand(path, (_: void, ifMatch) => api.post(`${path}/declarations`, { has_conflict: conflict, declaration: text.trim() }, ifMatchOptions(ifMatch)),
    { success: conflict ? 'Conflict declared: you cannot score or award this event' : 'Declaration recorded: you may score', onSuccess: onClose });
  return (
    <Dialog open title="Conflict-of-interest declaration" onClose={onClose}>
      {existing ? (
        <div className="space-y-3 text-sm">
          <p>You declared on {dateTime(existing.declaredAt)}: <span className="font-semibold">{existing.hasConflict ? 'conflict of interest' : 'no conflict'}</span>.</p>
          <p className="rounded bg-slate-50 p-2">{existing.declaration}</p>
          <p className="text-xs text-slate-500">A declaration cannot be changed or withdrawn.</p>
          <div className="flex justify-end"><Button onClick={onClose}>Close</Button></div>
        </div>
      ) : (
        <div className="space-y-3">
          <fieldset>
            <legend className="text-xs font-medium text-slate-700">I declare that</legend>
            <label className="mt-1 flex items-center gap-2 text-sm"><input type="radio" name="conflict" className="h-4 w-4" checked={!conflict} onChange={() => setConflict(false)} /> I have no personal, financial or family interest in any bidder</label>
            <label className="mt-1 flex items-center gap-2 text-sm"><input type="radio" name="conflict" className="h-4 w-4" checked={conflict} onChange={() => setConflict(true)} /> I have a conflict of interest (I will not score or award)</label>
          </fieldset>
          <Field label="Declaration (at least 10 characters)" required>{(id) => <Textarea id={id} value={text} onChange={(e) => setText(e.target.value)}
            placeholder={conflict ? 'Name the bidder and the interest' : 'I have no interest in any bidder of this event.'} />}</Field>
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={text.trim().length < 10} busy={declare.isPending} onClick={() => declare.mutate()}>Record declaration</Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}

function DisqualifyDialog({ path, rows, onClose }: { path: string; rows: CompareRow[]; onClose: () => void }) {
  const [supplier, setSupplier] = useState(rows[0]?.supplier ?? '');
  const [reason, setReason] = useState('');
  const go = useEventCommand(path, (_: void, ifMatch) => api.post(`${path}/disqualify`, { supplier, reason: reason.trim() }, ifMatchOptions(ifMatch)),
    { success: `${supplier} disqualified: the bid stays on record, leaves the ranking and earlier scenarios are marked stale`, onSuccess: onClose });
  return (
    <Dialog open title="Disqualify a bidder" onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-slate-700">The bid stays on record with the reason, leaves the ranking, the scenarios built on it become stale, the supplier is told and cannot bid again in a later round.</p>
        <Field label="Bidder" required>{(id) => <Select id={id} value={supplier} onChange={(e) => setSupplier(e.target.value)} options={rows.map((r) => ({ value: r.supplier, label: `${r.supplier} · rank ${r.rank} · ${inr(r.tcoMinor)}` }))} />}</Field>
        <Field label="Written reason (at least 10 characters)" required>{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Failed the technical gate and did not accept the quality plan" />}</Field>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="danger" disabled={!supplier || reason.trim().length < 10} busy={go.isPending} onClick={() => go.mutate()}>Disqualify</Button>
        </div>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- comparison matrix
export function ComparisonPanel({ event, path, comparison, loading, error, canManage }: {
  event: SourcingEvent; path: string; comparison?: Comparison; loading: boolean; error: ApiError | null; canManage: boolean;
}) {
  const [csv, setCsv] = useState<CsvDownload | null>(null);
  const [csvError, setCsvError] = useState<ApiError | null>(null);
  const exportCsv = useCommand(() => fetchCsv(`${path}/comparison.csv`), {
    success: (r) => `Exported ${r.rows ?? '?'} row(s), SHA-256 ${r.sha256?.slice(0, 12) ?? '–'}…`,
    onSuccess: (r) => { setCsv(r); setCsvError(null); saveFile(r); },
  });
  const [open, setOpen] = useState<string | null>(null);
  if (!canManage) return <p className="text-sm text-slate-600">The comparison is shown to users who manage sourcing events.</p>;
  if (['DRAFT', 'PUBLISHED', 'OPEN'].includes(event.status) || !event.unsealed_at) {
    return <p className="text-sm text-slate-600">The comparison is available after the bids are opened (see the Bids and opening tab). Reading it earlier is refused (423) and logged.</p>;
  }
  if (loading) return <Loading />;
  if (error) return error.status === 423 ? <SealedLock error={error} closeAt={event.close_at} /> : <ProblemBox error={error} />;
  if (!comparison) return null;
  const rows = comparison.bids;
  const multi = event.lines.length > 1;
  const manual = event.criteria.filter((c) => c.code !== 'PRICE_TCO');
  const bm = comparison.benchmark;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Valid bidders" value={`${comparison.validBidders}`} hint={`minimum ${comparison.minBidders ?? '–'} · ${comparison.competitive == null ? 'not set' : comparison.competitive ? 'competitive' : 'NOT competitive'}`}
          tone={comparison.competitive === false ? 'warn' : 'default'} />
        <Kpi label="Baseline" value={inr(comparison.baselineMinor)} hint={label(comparison.baselineMethod)} />
        <Kpi label="Price scoring" value={label(comparison.scoringMethod)} hint={`round ${comparison.round} · ${comparison.currency}${comparison.referenceDate ? ` at ${date(comparison.referenceDate)}` : ''}`} />
        <Kpi label="Should-cost / unit" value={comparison.shouldCost ? `₹${comparison.shouldCost.unitCost}` : '–'}
          hint={bm && bm.lowMinor != null ? `benchmark ${inr(bm.lowMinor)} to ${inr(bm.highMinor)}` : undefined} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button busy={exportCsv.isPending} onClick={() => exportCsv.mutate(undefined, { onError: (e) => setCsvError(e) })}>Export comparison CSV</Button>
        <p className="text-xs text-slate-500">Allowed after the opening. The SHA-256 of the file is audited (COMPARISON_EXPORTED) so a copy that left the system can be matched.</p>
      </div>
      {csvError && <ProblemBox error={csvError} />}
      {csv && (
        <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
          <p className="font-semibold">{csv.filename}: {csv.rows ?? '?'} row(s), {csv.bytes.toLocaleString('en-IN')} bytes</p>
          <p className="mt-1 break-all font-mono text-[11px]">SHA-256 {csv.sha256 ?? 'not provided by the server'}</p>
        </div>
      )}

      {!rows.length ? <Empty title="No evaluated bids" hint="Nobody bid, or every bid was withdrawn, disqualified or invalid." /> : (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <caption className="sr-only">Bid comparison ranked by total cost of ownership</caption>
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="px-3 py-2 text-left">#</th>
                <th scope="col" className="px-3 py-2 text-left">Supplier</th>
                <th scope="col" className="px-3 py-2 text-right">{multi ? 'Annual price' : 'Price / unit'}</th>
                <th scope="col" className="px-3 py-2 text-right">{multi ? 'Annual TCO' : 'TCO / unit'}</th>
                <th scope="col" className="px-3 py-2 text-right">Price score</th>
                {manual.map((c) => <th key={c.code} scope="col" className="px-3 py-2 text-right">{c.code.replace(/_/g, ' ')}</th>)}
                <th scope="col" className="px-3 py-2 text-right">Weighted</th>
                <th scope="col" className="px-3 py-2 text-left">Gate</th>
                <th scope="col" className="px-3 py-2 text-right">Lead</th>
                <th scope="col" className="px-3 py-2 text-left">Checks</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {rows.map((r) => (
                <Fragment key={r.bidId}>
                  <tr className="align-top">
                    <td className="px-3 py-2 tabular-nums font-semibold">{r.rank}{r.tiedWithPrevious && <span className="ml-1 rounded bg-amber-50 px-1 py-0.5 text-[10px] font-semibold uppercase text-amber-800" title="Same total cost as the bid above: ranked by weighted score, then earlier submission, then supplier code">tie</span>}</td>
                    <td className="px-3 py-2">
                      <Link href={`/pic/suppliers/${encodeURIComponent(r.supplier)}`} className="font-medium text-[#1A56DB] hover:underline">{r.supplier}</Link>
                      <span className="ml-1 text-xs text-slate-500">round {r.round}</span>
                      {r.validUntil && <p className="text-[11px] text-slate-500">valid until {date(r.validUntil)}</p>}
                      {multi && !r.complete && <p className="text-[11px] font-semibold text-amber-800">{r.coverage.bid}/{r.coverage.of} lines</p>}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{inr(r.priceMinor)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      <button type="button" aria-expanded={open === r.bidId} onClick={() => setOpen(open === r.bidId ? null : r.bidId)}
                        className="font-semibold text-[#1A56DB] underline decoration-dotted focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1A56DB]">
                        {inr(r.tcoMinor)}<span className="sr-only"> show the cost stack of {r.supplier}</span>
                      </button>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{r.priceScore ?? '–'}</td>
                    {manual.map((c) => (
                      <td key={c.code} className="px-3 py-2 text-right tabular-nums">{r.scores?.[c.code] ?? <span className="text-slate-400">–</span>}{r.autoScores?.[c.code] && <span className="ml-1 text-[10px] uppercase text-slate-400">data</span>}</td>
                    ))}
                    <td className="px-3 py-2 text-right font-semibold tabular-nums">{r.weightedScore ?? '–'}</td>
                    <td className="px-3 py-2"><GateChip row={r} /></td>
                    <td className="px-3 py-2 text-right tabular-nums">{r.leadTimeDays} d</td>
                    <td className="px-3 py-2">
                      <div className="flex max-w-[16rem] flex-wrap gap-1">
                        {r.tcoIncomplete && <Chip tone="red" title={`Missing TCO input: ${r.tcoMissing.join(', ')}`}>TCO incomplete: {r.tcoMissing.join(', ')}</Chip>}
                        {!r.capacityVerified && <Chip tone="amber" title="No bid capacity and no digital-twin capacity figure">capacity not verified</Chip>}
                        {r.capacityVerified && <Chip tone="slate" title="Lower of the offered and the twin's free capacity">capacity {qty(r.verifiedCapacityPerMonth)} / month</Chip>}
                        {(r.unscored?.length ?? 0) > 0 && <Chip tone="amber" title="Criteria nobody scored count as zero in the weighted score">unscored: {r.unscored!.join(', ')}</Chip>}
                        {r.flags.map((f) => <Chip key={f} tone="red">{FLAG_TEXT[f] ?? f}</Chip>)}
                        {r.shouldCostDeltaMinor != null && <Chip tone={r.shouldCostDeltaMinor > 0 ? 'amber' : 'green'}>vs should-cost {r.shouldCostDeltaMinor > 0 ? '+' : ''}{inr(r.shouldCostDeltaMinor)}</Chip>}
                        {r.lateDeliveryProb != null && <Chip tone="slate">late {pctOf(r.lateDeliveryProb)}</Chip>}
                      </div>
                    </td>
                  </tr>
                  {open === r.bidId && (
                    <tr className="bg-slate-50/60">
                      <td colSpan={9 + manual.length} className="px-3 py-3">
                        <TcoDetail row={r} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          <p className="border-t border-slate-100 px-3 py-2 text-xs text-slate-500">
            TCO = price + freight + duty + packaging + carrying cost + quality cost - value of payment terms, in INR per base unit at the event&apos;s reference date. Equal total cost is ranked by weighted score,
            then earlier submission, then supplier code. Open the TCO of a bid for its stack.
          </p>
        </div>
      )}

      {comparison.excludedBids.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Left out of the evaluation</h3>
          <ul className="space-y-1 text-sm">
            {comparison.excludedBids.map((b, i) => <li key={`${b.supplier}-${i}`}><span className="font-medium">{b.supplier}</span> round {b.round} <StatusChip status={b.status} /> {b.reason && <span className="text-slate-600">{b.reason}</span>}</li>)}
          </ul>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Abnormally low or high bids">
          {!comparison.screens.outliers.length ? <p className="text-sm text-slate-600">No bid is an outlier against the median, the z-score limit or the should-cost.</p> : (
            <ul className="space-y-1 text-sm">{comparison.screens.outliers.map((o, i) => <li key={`${o.supplier}-${o.flag}-${i}`}><span className="font-medium">{o.supplier}</span> <Chip tone="red">{FLAG_TEXT[o.flag] ?? o.flag}</Chip> <span className="text-slate-600">{o.detail}</span></li>)}</ul>
          )}
        </Card>
        <Card title="Collusion hints">
          {!comparison.screens.collusion.length ? <p className="text-sm text-slate-600">No identical totals, copied line pattern or shared master data between the bidders.</p> : (
            <ul className="space-y-1 text-sm">{comparison.screens.collusion.map((h, i) => <li key={i}><span className="font-mono text-xs font-semibold">{h.hint}</span> {h.suppliers.join(' + ')} <span className="text-slate-600">{h.detail}</span></li>)}</ul>
          )}
          <p className="mt-2 text-xs text-slate-500">Hints for a human to look at, not findings. Not checked (PIC holds no such data): {comparison.screens.notChecked.join('; ')}.</p>
        </Card>
      </div>
      {bm && Object.keys(bm.points).length > 0 && (
        <Card title="Benchmark band">
          <ul className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            {Object.entries(bm.points).map(([k, p]) => <li key={k}>{label(k)}: <span className="font-semibold tabular-nums">{inr(p.priceMinor)}</span> <span className="text-xs text-slate-500">{p.source}{p.asOf ? ` · ${date(p.asOf)}` : ''}</span></li>)}
          </ul>
        </Card>
      )}
    </div>
  );
}

function Chip({ tone, children, title }: { tone: 'red' | 'amber' | 'green' | 'slate'; children: React.ReactNode; title?: string }) {
  const c = { red: 'bg-red-50 text-red-800 ring-red-200', amber: 'bg-amber-50 text-amber-800 ring-amber-200', green: 'bg-emerald-50 text-emerald-800 ring-emerald-200', slate: 'bg-slate-100 text-slate-700 ring-slate-200' }[tone];
  return <span title={title} className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold ring-1 ring-inset ${c}`}>{children}</span>;
}

function TcoDetail({ row }: { row: CompareRow }) {
  return (
    <div className="space-y-3">
      {row.lines.map((l) => (
        <div key={l.line} className="grid gap-3 lg:grid-cols-[minmax(0,22rem)_1fr]">
          <div>
            <p className="mb-1 text-xs font-semibold text-slate-700">
              {row.lines.length > 1 ? `Line ${l.line}${l.lot ? ` (lot ${l.lot})` : ''} · ` : ''}{row.supplier} · {l.currency}{l.quotedPriceMinor != null ? ` ${(l.quotedPriceMinor / 100).toFixed(2)} quoted` : ''}
              {l.fxRate ? ` at ${l.fxRate}` : ''}{l.incoterm ? ` · ${l.incoterm}` : ''}{l.origin ? ` · ${l.origin.toLowerCase()}` : ''}
            </p>
            <TcoStack parts={l.tco} totalMinor={l.tcoMinor} missing={l.tcoMissing} />
            {l.tcoIncomplete && <p role="status" className="mt-1 text-xs font-semibold text-red-700">Incomplete: {l.tcoMissing.join(', ')} could not be determined and is not counted as zero. An award on this bid needs a written rationale.</p>}
            <p className="mt-1 text-[11px] text-slate-500">MOQ {l.moq ?? '–'} · capacity {qty(l.verifiedCapacityPerMonth)} {l.capacityVerified ? '(verified)' : '(not verified)'} · payment {l.paymentTermsDays} d</p>
          </div>
          <div>{(l.tcoTrace ?? l.trace)?.length ? <TraceTable trace={(l.tcoTrace ?? l.trace) as never} /> : <p className="text-xs text-slate-500">The component trace (formula and inputs) of a submitted bid line is not part of this view; the simulator tab reproduces it for a line.</p>}</div>
        </div>
      ))}
    </div>
  );
}

