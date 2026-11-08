'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { ObjectPage } from '@/components/pic/object';
import { Button, DataTable, Facts, StatusChip } from '@/components/pic/ui';
import { api, readSessionUser } from '@/lib/pic/api';
import { date, dateTime, inr, label, qty } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { Comparison, EVALUATE_ROLES, ifMatchOptions, MANAGE_ROLES, useCan, useEventCommand, useEventDoc } from '../_lib';
import { TcoSimulator } from '../_tco';
import { AuctionPanel, ClarificationsPanel } from './_ops';
import { AwardPanel, CloneDialog, HandoffPanel, HistoryPanel } from './_award';
import { BidsOpeningPanel, ComparisonPanel, EvaluationPanel } from './_bids';
import {
  AwardDialog, CANCELLABLE, CancelEventDialog, CustomSplitDialog, Criterion, EventLine, ExtendDialog, Invitee, LineMatrixPanel, normaliseScenario, RoundDialog, ScenariosPanel,
  ScoreDialog, SourcingEvent,
} from './_parts';

const PRE_CLOSE = ['DRAFT', 'PUBLISHED', 'OPEN'];

export default function SourcingEventPage() {
  const { ref } = useParams<{ ref: string }>();
  const path = `/sourcing/events/${encodeURIComponent(ref)}`;
  const { data: ev, isLoading, error } = useEventDoc<SourcingEvent>(path);
  const can = useCan();
  const canManage = can(MANAGE_ROLES);
  const canScore = can(EVALUATE_ROLES);
  // POST …/cancel: the event owner or a category manager (the server also checks the manager's categories).
  const roles = readSessionUser()?.roles;
  const canCancel = !!ev && CANCELLABLE.includes(ev.status) && canManage
    && (!roles || roles.length === 0 || roles.includes('CATEGORY_MANAGER') || (!!ev.owner_id && readSessionUser()?.id === ev.owner_id));

  const unsealed = !!ev && !PRE_CLOSE.includes(ev.status) && !!ev.unsealed_at;
  const comparison = useApi<Comparison>(ev && canManage && unsealed ? `${path}/comparison` : null);
  const [dialog, setDialog] = useState<'score' | 'round' | 'award' | 'cancel' | 'clone' | 'custom' | 'extend' | null>(null);
  const [awardScenario, setAwardScenario] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(t);
  }, []);

  const publish = useEventCommand(path, (_: void, ifMatch) => api.post(`${path}/publish`, {}, ifMatchOptions(ifMatch)), {
    success: 'Published – weights locked, bids sealed until the opening' });
  const close = useEventCommand(path, (_: void, ifMatch) => api.post<{ unsealed: number; awaitingOpening?: boolean }>(`${path}/close`, {}, ifMatchOptions(ifMatch)), {
    success: (r) => (r.awaitingOpening ? 'Event closed – the bids stay sealed until two people open them' : `Event closed – ${r.unsealed} bid(s) unsealed and evaluated on TCO`) });
  const build = useEventCommand(path, (_: void, ifMatch) => api.post<unknown[]>(`${path}/scenarios`, {}, ifMatchOptions(ifMatch)), { success: (r) => `${r.length} award scenario(s) built` });

  const scenarios = (ev?.scenarios ?? []).map(normaliseScenario);
  const weightTotal = ev?.criteria.reduce((s, c) => s + c.weight, 0) ?? 0;
  const auction = ev?.type === 'REVERSE_AUCTION';
  // A reverse auction closes at its live end, which soft-close bids may have pushed past the scheduled close.
  const closesAt = ev ? (auction && ev.auction_ends_at ? ev.auction_ends_at : ev.close_at) : '';
  const closeReached = ev ? now >= new Date(closesAt).getTime() : false;
  const evaluating = ev?.status === 'UNDER_EVALUATION';
  const sc = ev?.should_cost;
  const cons = ev?.constraints;
  const started = !!ev && ev.status !== 'DRAFT';
  const bc = ev?.budget_check;
  const rows = comparison.data?.bids ?? [];

  return (
    <>
      <ObjectPage
        type="SOURCING_EVENT" docRef={ref} eyebrow={`SRC-03 · ${ev ? ev.type.replace(/_/g, ' ') : 'Sourcing event'} · ${ev?.category ?? ''}`}
        loading={isLoading} error={error}
        title={<>{ev?.number} <span className="text-base font-normal text-slate-500">{ev?.title}</span></>}
        status={ev?.status}
        actions={ev && (
          <>
            {canManage && ev.status === 'DRAFT' && (
              <Button variant="primary" busy={publish.isPending} onClick={() => publish.mutate()} disabled={weightTotal !== 100}
                title={weightTotal !== 100 ? `Weights total ${weightTotal}; they must total 100` : undefined}>Publish</Button>
            )}
            {canManage && ev.status === 'OPEN' && (
              <Button variant="primary" busy={close.isPending} disabled={!closeReached} onClick={() => close.mutate()}
                title={!closeReached ? `Can close after ${dateTime(closesAt)}` : undefined}>
                {closeReached ? (auction ? 'Close auction & evaluate' : 'Close & unseal bids') : `Closes ${dateTime(closesAt)}`}
              </Button>
            )}
            {canManage && !auction && ['PUBLISHED', 'OPEN'].includes(ev.status) && <Button onClick={() => setDialog('extend')}>Extend deadline</Button>}
            {canManage && evaluating && <Button onClick={() => setDialog('round')}>New round</Button>}
            {canManage && evaluating && <Button busy={build.isPending} onClick={() => build.mutate()}>{scenarios.length ? 'Rebuild scenarios' : 'Build scenarios'}</Button>}
            {canManage && evaluating && scenarios.some((s) => s.feasible && !s.superseded) && (
              <Button variant="primary" onClick={() => { setAwardScenario(null); setDialog('award'); }}>Award</Button>
            )}
            {canManage && <Button onClick={() => setDialog('clone')}>Clone</Button>}
            {canCancel && <Button variant="danger" onClick={() => setDialog('cancel')}>Cancel event</Button>}
          </>
        )}
        facts={ev && (
          <div className="space-y-4">
            <Facts items={[
              ['Round', `${ev.round}`],
              ['Bids open', ev.open_at ? dateTime(ev.open_at) : ev.published_at ? 'at publication' : '–'],
              ['Questions close', ev.clarification_close_at ? dateTime(ev.clarification_close_at) : '–'],
              ['Bids close', dateTime(ev.close_at)],
              ['Published', dateTime(ev.published_at)],
              ['Closed / unsealed', ev.unsealed_at ? dateTime(ev.unsealed_at) : started && PRE_CLOSE.includes(ev.status) ? 'sealed' : ev.status === 'CLOSED' ? 'sealed (waiting for the opening)' : '–'],
              ['Price scoring', ev.scoring_method ? label(ev.scoring_method) : '–'],
              ['Pricing (reference) date', ev.reference_date ? date(ev.reference_date) : '–'],
              ['Minimum bidders', ev.min_bidders != null ? `${ev.min_bidders}${ev.competitive == null ? '' : ev.competitive ? ' · competitive' : ' · NOT competitive'}` : '–'],
              ['Purpose code', ev.purpose_code ?? (ev.status === 'DRAFT' ? 'taken from the requirements at publication' : '–')],
              ['Need date', ev.need_date ? date(ev.need_date) : '–'],
              [ev.lines.length > 1 ? 'Baseline (annual value)' : 'Baseline / unit', <>{inr(ev.baseline_price_minor)} <span className="text-xs font-normal text-slate-500">{label(ev.baseline_method)}</span></>],
              ...(ev.bundle ? [['Bundled from', `${ev.bundle.sourceLines} requirement line(s) · ${ev.bundle.requisitions.join(', ')}${ev.bundle.ref ? ` · ${ev.bundle.ref}` : ''}`] as [string, string]] : []),
              ['Should-cost / unit', sc ? `₹${sc.unitCost}` : '–'],
              ['Award constraints', cons ? `≤ ${cons.max_suppliers ?? '–'} suppliers per line · share ${pctStr(cons.min_share)}–${pctStr(cons.max_share)}${riskStr(cons)}` : '–'],
              ['Savings target', ev.savings_target_pct ? `${ev.savings_target_pct}%` : '–'],
              ...(ev.template_code ? [['From template', ev.template_code] as [string, string]] : []),
              ...(ev.cloned_from ? [['Cloned from', <Link key="c" className="text-[#1A56DB] hover:underline" href={`/pic/sourcing/${encodeURIComponent(ev.cloned_from)}`}>{ev.cloned_from}</Link>] as [string, React.ReactNode]] : []),
              ...(ev.rule_versions && Object.keys(ev.rule_versions).length ? [['Rule versions', <span key="r" className="font-mono text-xs">{Object.entries(ev.rule_versions).map(([k, v]) => `${k} ${v}`).join(' · ')}</span>] as [string, React.ReactNode]] : []),
            ]} />
            {bc && bc.outcome !== 'OFF' && (
              <div className={`rounded-lg p-3 text-sm ${bc.outcome === 'EXCEEDED_JUSTIFIED' ? 'bg-amber-50 text-amber-900' : 'bg-slate-50 text-slate-700'}`} role="status">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Category budget check at publication</p>
                <p className="mt-1">
                  {bc.outcome === 'NOT_APPLICABLE' ? `No approved category plan with a budget for ${bc.fiscalYear ?? 'this year'}: not applicable.` : (
                    <>{label(bc.outcome)}: plan {bc.plan} {bc.fiscalYear}, budget {inr(bc.budgetMinor)}, committed {inr(bc.committedMinor)}, this event adds {inr(bc.incrementalMinor)}; projected {inr(bc.projectedMinor)} = {bc.usedPct}% ({bc.mode} stop).</>
                  )}
                  {(bc.justification ?? ev.budget_justification) && <span className="block"><span className="font-semibold">Justification:</span> {bc.justification ?? ev.budget_justification}</span>}
                </p>
              </div>
            )}
            {!bc && ev.budget_justification && <p className="text-sm"><span className="font-semibold">Budget justification:</span> {ev.budget_justification}</p>}
            {sc && (
              <div className="rounded-lg bg-slate-50 p-3 text-sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Should-cost model ({sc.model})</p>
                <p className="mt-1 text-slate-700">
                  {sc.material !== undefined
                    ? <>Material ₹{money2(sc.material)} + conversion ₹{money2(sc.conversion)} + tooling ₹{money2(sc.tooling)} + packaging ₹{money2(sc.packaging)} = ₹{money2(sc.subtotal)}; + {sc.overheadMarginPct}% overhead &amp; margin = <span className="font-semibold">₹{sc.unitCost} / unit</span></>
                    : <>Subtotal ₹{money2(sc.subtotal)} + {sc.overheadMarginPct}% margin = <span className="font-semibold">₹{sc.unitCost} / unit</span></>}
                </p>
              </div>
            )}
            {ev.status === 'PUBLISHED' && (
              <p className="text-sm text-slate-600">Published: suppliers see the requirement and may ask questions{ev.clarification_close_at ? ` until ${dateTime(ev.clarification_close_at)}` : ''}; bids are accepted from {ev.open_at ? dateTime(ev.open_at) : 'the scheduled opening'} to {dateTime(ev.close_at)}.</p>
            )}
            {ev.status === 'OPEN' && !auction && (
              <p className="text-sm text-slate-600">Bidding is open in round {ev.round}. {closeReached ? 'Close time reached – close the event to open the bids.' : `Bids stay sealed until ${dateTime(ev.close_at)}.`}</p>
            )}
            {ev.status === 'OPEN' && auction && (
              <p className="text-sm text-slate-600">Live reverse auction in round {ev.round}, ending {dateTime(closesAt)}{closesAt !== ev.close_at ? ` (extended from ${dateTime(ev.close_at)})` : ''}. {closeReached ? 'The auction has ended – close it to evaluate the final prices.' : 'Follow the ladder in the Live auction tab.'}</p>
            )}
          </div>
        )}
        lines={ev && (
          <DataTable<EventLine> rows={ev.lines} empty="No requirement lines" columns={[
            { key: 'line_no', header: 'Line' },
            { key: 'description', header: 'Item' },
            { key: 'plant', header: 'Plant' },
            { key: 'annual_qty', header: 'Annual qty', align: 'right', render: (l) => qty(l.annual_qty, l.uom) },
            { key: 'monthly_qty', header: 'Monthly qty', align: 'right', render: (l) => qty(l.monthly_qty, l.uom) },
            { key: 'lot_code', header: 'Lot', render: (l) => l.lot_code ?? '–' },
            { key: 'baseline_price_minor', header: 'Baseline / unit', align: 'right', render: (l) => (l.baseline_price_minor ? inr(l.baseline_price_minor) : '–') },
            { key: 'need_date', header: 'Need date', render: (l) => (l.need_date ? date(l.need_date) : '–') },
            { key: 'pr_line_no', header: 'Requisition line', render: (l) => (l.pr_line_no ? `${l.requisition ? `${l.requisition} / ` : ''}line ${l.pr_line_no}` : '–') },
          ]} />
        )}
        extraTabs={ev ? [
          ...(auction ? [{ id: 'auction', label: ev.status === 'OPEN' ? 'Live auction' : 'Auction', content: <AuctionPanel path={path} status={ev.status} canManage={canManage} /> }] : []),
          {
            id: 'criteria', label: `Criteria (${weightTotal}%)`, content: (
              <div>
                <DataTable<Criterion> rows={ev.criteria} empty="No scoring criteria" columns={[
                  { key: 'code', header: 'Code', render: (c) => <span className="font-mono text-xs">{c.code}</span> },
                  { key: 'name', header: 'Criterion' },
                  { key: 'weight', header: 'Weight', align: 'right', render: (c) => `${c.weight}%` },
                  { key: 'min_score', header: 'Technical gate', align: 'right', render: (c) => (c.min_score != null ? `minimum ${String(c.min_score)}` : '–') },
                  { key: 'how', header: 'Scored by', render: (c) => (c.code === 'PRICE_TCO' ? `Computed from TCO (${label(ev.scoring_method)})` : c.data_source && c.data_source !== 'MANUAL' ? `Platform data at close (${label(c.data_source)})` : 'Evaluators (0–100)') },
                ]} />
                <p className={`mt-2 text-sm ${weightTotal === 100 ? 'text-slate-600' : 'font-medium text-red-700'}`}>
                  Weights total {weightTotal}/100{ev.weights_locked ? ' · locked at publish' : weightTotal !== 100 ? ' – must total 100 before publishing' : ''}.
                </p>
              </div>
            ),
          },
          {
            id: 'invitees', label: `Invitations (${ev.invitees.length})`, content: (
              <DataTable<Invitee> rows={ev.invitees} rowHref={(i) => `/pic/suppliers/${encodeURIComponent(i.code)}`} empty="No suppliers invited" columns={[
                { key: 'code', header: 'Supplier' },
                { key: 'name', header: 'Name' },
                { key: 'categoryStatus', header: `Status in ${ev.category}`, render: (i) => <StatusChip status={i.categoryStatus} /> },
                { key: 'waiver', header: 'Waiver', render: (i) => i.waiver ?? '–' },
                { key: 'bid', header: `Bid round ${ev.round}`, render: (i) => {
                  const b = ev.bids.find((x) => x.supplier === i.code && x.round === ev.round);
                  return b ? <StatusChip status={b.status} /> : <span className="text-slate-500">no bid yet</span>;
                } },
              ]} />
            ),
          },
          ...(started ? [{ id: 'clarifications', label: 'Clarifications', content: <ClarificationsPanel path={path} canManage={canManage} /> }] : []),
          ...(started ? [{ id: 'bids', label: 'Bids and opening', content: <BidsOpeningPanel event={ev} path={path} canManage={canManage} /> }] : []),
          ...(started ? [{
            id: 'evaluation', label: 'Evaluation', content: (
              <EvaluationPanel event={ev} path={path} canManage={canManage} canScore={canScore} comparison={comparison.data} onScore={() => setDialog('score')} />
            ),
          }] : []),
          ...(started ? [{
            id: 'comparison', label: 'Comparison', content: (
              <div className="space-y-5">
                <ComparisonPanel event={ev} path={path} comparison={comparison.data} loading={comparison.isLoading} error={comparison.error} canManage={canManage} />
                {unsealed && canManage && ev.lines.length > 1 && <LineMatrixPanel event={ev} />}
              </div>
            ),
          }] : []),
          ...(canManage ? [{
            id: 'tco', label: 'TCO simulator', content: <TcoSimulator suppliers={ev.invitees.map((i) => i.code)} defaultCategory={ev.category} defaultSupplier={ev.invitees[0]?.code} />,
          }] : []),
          ...(started ? [{
            id: 'scenarios', label: `Award scenarios (${scenarios.length})`, content: (
              <ScenariosPanel event={ev} scenarios={scenarios} canManage={canManage} canAward={canManage && evaluating}
                onAward={(id) => { setAwardScenario(id); setDialog('award'); }} onCustom={() => setDialog('custom')} />
            ),
          }] : []),
          ...(started ? [{ id: 'award', label: `Award (${ev.awardDecisions.length})`, content: <AwardPanel event={ev} scenarios={scenarios} /> }] : []),
          ...(['AWARD_PENDING', 'AWARDED'].includes(ev.status) ? [{ id: 'handoff', label: 'Hand-off', content: <HandoffPanel event={ev} path={path} canManage={canManage} /> }] : []),
          ...(started && canManage ? [{ id: 'history', label: 'History', content: <HistoryPanel path={path} /> }] : []),
        ] : []}
      />
      {ev && evaluating && (
        <p className="mt-3 text-xs text-slate-500">
          Next: declare your conflict of interest, score the manual criteria, optionally run another sealed round, then build scenarios and propose an award. See also the{' '}
          <Link className="text-[#1A56DB] hover:underline" href="/pic/tasks">task inbox</Link> for approvals.
        </p>
      )}
      {ev && dialog === 'score' && <ScoreDialog event={ev} matrix={rows} onClose={() => setDialog(null)} />}
      {ev && dialog === 'round' && <RoundDialog event={ev} onClose={() => setDialog(null)} />}
      {ev && dialog === 'extend' && <ExtendDialog event={ev} onClose={() => setDialog(null)} />}
      {ev && dialog === 'award' && <AwardDialog event={ev} scenarios={scenarios} comparison={comparison.data} initial={awardScenario} onClose={() => setDialog(null)} />}
      {ev && dialog === 'custom' && <CustomSplitDialog event={ev} rows={rows} onClose={() => setDialog(null)} />}
      {ev && dialog === 'cancel' && <CancelEventDialog event={ev} onClose={() => setDialog(null)} />}
      {ev && dialog === 'clone' && <CloneDialog event={ev} onClose={() => setDialog(null)} />}
    </>
  );
}

function riskStr(c: Record<string, unknown>) {
  const parts = [
    c.max_risk_score !== undefined ? `risk ≤ ${String(c.max_risk_score)}` : '', c.max_single_source_pct !== undefined ? `no supplier above ${String(c.max_single_source_pct)}%` : '',
    c.max_conditional_share_pct !== undefined ? `conditional ≤ ${String(c.max_conditional_share_pct)}%` : '', c.max_total_suppliers !== undefined ? `≤ ${String(c.max_total_suppliers)} suppliers in all` : '',
  ].filter(Boolean);
  return parts.length ? ` · ${parts.join(' · ')}` : '';
}

function pctStr(v: string | number | undefined) {
  return v === undefined || v === null ? '–' : `${Math.round(Number(v) * 100)}%`;
}

/** Should-cost amounts come back with many decimals; show rupees and paise. */
function money2(v: string | number | null | undefined) {
  return v === null || v === undefined || v === '' ? '–' : Number(v).toFixed(2);
}
