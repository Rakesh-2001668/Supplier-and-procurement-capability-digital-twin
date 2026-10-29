'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { ObjectPage } from '@/components/pic/object';
import { Button, DataTable, Facts, StatusChip } from '@/components/pic/ui';
import { api, readSessionUser } from '@/lib/pic/api';
import { dateTime, inr, label, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import {
  AwardDialog, BidsPanel, CANCELLABLE, CancelEventDialog, Criterion, EventLine, Invitee, MatrixRow, normaliseScenario, RoundDialog, ScenariosPanel,
  ScoreDialog, SourcingEvent,
} from './_parts';
import { AuctionPanel, ClarificationsPanel } from './_ops';

const PRE_CLOSE = ['DRAFT', 'PUBLISHED', 'OPEN'];
const MANAGE = ['BUYER', 'CATEGORY_MANAGER'];
const EVALUATE = ['CATEGORY_MANAGER', 'QUALITY_INSPECTOR'];

const noSubscribe = () => () => {};

/** Roles from the session cookie; null while rendering on the server. */
function useRoles() {
  const cookie = useSyncExternalStore(noSubscribe, () => document.cookie, () => null);
  return useMemo(() => (cookie === null ? null : readSessionUser()?.roles ?? []), [cookie]);
}

export default function SourcingEventPage() {
  const { ref } = useParams<{ ref: string }>();
  const path = `/sourcing/events/${encodeURIComponent(ref)}`;
  const { data: ev, isLoading, error } = useApi<SourcingEvent>(path);
  const roles = useRoles();
  const can = (allowed: string[]) => !!roles && (roles.length === 0 || roles.some((r) => allowed.includes(r)));
  const canManage = can(MANAGE);
  const canScore = can(EVALUATE);
  // POST …/cancel: the event owner or a category manager (the server also checks the manager's categories).
  const canCancel = !!ev && CANCELLABLE.includes(ev.status) && !!roles
    && (roles.length === 0 || roles.includes('CATEGORY_MANAGER') || (!!ev.owner_id && readSessionUser()?.id === ev.owner_id));

  const sealed = !ev || PRE_CLOSE.includes(ev.status) || !ev.unsealed_at;
  const [peek, setPeek] = useState(false);
  const bids = useApi<MatrixRow[]>(ev && (!sealed || peek) ? `${path}/bids` : null);
  const [dialog, setDialog] = useState<'score' | 'round' | 'award' | 'cancel' | null>(null);
  const [awardScenario, setAwardScenario] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(t);
  }, []);

  const publish = useCommand(() => api.post(`${path}/publish`), { success: 'Published – weights locked, bids sealed until close' });
  const close = useCommand(() => api.post<{ unsealed: number }>(`${path}/close`), {
    success: (r) => `Event closed – ${r.unsealed} bid(s) unsealed and evaluated on TCO`,
    onSuccess: () => setPeek(true),
  });
  const build = useCommand(() => api.post<unknown[]>(`${path}/scenarios`), { success: (r) => `${r.length} award scenario(s) built` });

  const scenarios = (ev?.scenarios ?? []).map(normaliseScenario);
  const weightTotal = ev?.criteria.reduce((s, c) => s + c.weight, 0) ?? 0;
  const auction = ev?.type === 'REVERSE_AUCTION';
  // A reverse auction closes at its live end, which soft-close bids may have pushed past the scheduled close.
  const closesAt = ev ? (auction && ev.auction_ends_at ? ev.auction_ends_at : ev.close_at) : '';
  const closeReached = ev ? now >= new Date(closesAt).getTime() : false;
  const evaluating = ev?.status === 'UNDER_EVALUATION';
  const sc = ev?.should_cost;
  const cons = ev?.constraints;

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
            {canScore && evaluating && <Button onClick={() => setDialog('score')} disabled={!bids.data?.length}>Score bids</Button>}
            {canManage && evaluating && <Button onClick={() => setDialog('round')}>New round</Button>}
            {canManage && evaluating && <Button busy={build.isPending} onClick={() => build.mutate()}>{scenarios.length ? 'Rebuild scenarios' : 'Build scenarios'}</Button>}
            {canManage && evaluating && scenarios.some((s) => s.feasible) && (
              <Button variant="primary" onClick={() => { setAwardScenario(null); setDialog('award'); }}>Award</Button>
            )}
            {canCancel && <Button variant="danger" onClick={() => setDialog('cancel')}>Cancel event</Button>}
          </>
        )}
        facts={ev && (
          <div className="space-y-4">
            <Facts items={[
              ['Round', `${ev.round}`],
              ['Close', dateTime(ev.close_at)],
              ['Published', dateTime(ev.published_at)],
              ['Closed / unsealed', ev.unsealed_at ? dateTime(ev.unsealed_at) : sealed && ev.status !== 'DRAFT' ? 'sealed' : '–'],
              ['Baseline / unit', <>{inr(ev.baseline_price_minor)} <span className="text-xs font-normal text-slate-500">{label(ev.baseline_method)}</span></>],
              ['Should-cost / unit', sc ? `₹${sc.unitCost}` : '–'],
              ['Award constraints', cons ? `≤ ${cons.max_suppliers ?? '–'} suppliers · share ${pctStr(cons.min_share)}–${pctStr(cons.max_share)}` : '–'],
              ['Savings target', ev.savings_target_pct ? `${ev.savings_target_pct}%` : '–'],
            ]} />
            {sc && (
              <div className="rounded-lg bg-slate-50 p-3 text-sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Should-cost model ({sc.model})</p>
                <p className="mt-1 text-slate-700">
                  Material ₹{sc.material} + conversion ₹{sc.conversion} + tooling ₹{sc.tooling} + packaging ₹{sc.packaging} = ₹{sc.subtotal};
                  + {sc.overheadMarginPct}% overhead &amp; margin = <span className="font-semibold">₹{sc.unitCost} / unit</span>
                </p>
              </div>
            )}
            {ev.status === 'OPEN' && !auction && (
              <p className="text-sm text-slate-600">Bidding is open in round {ev.round}. {closeReached ? 'Close time reached – close the event to unseal the bids.' : `Bids stay sealed until ${dateTime(ev.close_at)}.`}</p>
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
            { key: 'pr_line_no', header: 'Requisition line', render: (l) => (l.pr_line_no ? `line ${l.pr_line_no}` : '–') },
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
                  { key: 'how', header: 'Scored by', render: (c) => (c.code === 'PRICE_TCO' ? 'Computed from TCO' : 'Evaluators (0–100)') },
                ]} />
                <p className={`mt-2 text-sm ${weightTotal === 100 ? 'text-slate-600' : 'font-medium text-red-700'}`}>
                  Weights total {weightTotal}/100{ev.weights_locked ? ' · locked at publish' : weightTotal !== 100 ? ' – must total 100 before publishing' : ''}.
                </p>
              </div>
            ),
          },
          {
            id: 'invitees', label: `Invitees (${ev.invitees.length})`, content: (
              <DataTable<Invitee> rows={ev.invitees} rowHref={(i) => `/pic/suppliers/${encodeURIComponent(i.code)}`} empty="No suppliers invited" columns={[
                { key: 'code', header: 'Supplier' },
                { key: 'name', header: 'Name' },
                { key: 'categoryStatus', header: `Status in ${ev.category}`, render: (i) => <StatusChip status={i.categoryStatus} /> },
                { key: 'waiver', header: 'Waiver', render: (i) => i.waiver ?? '–' },
                { key: 'bid', header: `Bid round ${ev.round}`, render: (i) => {
                  const b = ev.bids.find((x) => x.supplier === i.code && x.round === ev.round);
                  return b ? <StatusChip status={b.status} /> : <span className="text-slate-500">none yet</span>;
                } },
              ]} />
            ),
          },
          {
            id: 'bids', label: 'Bids & evaluation', content: (
              <BidsPanel event={ev} sealed={sealed} requested={!sealed || peek} onRequest={() => setPeek(true)}
                matrix={bids.data} loading={bids.isLoading} error={bids.error} />
            ),
          },
          ...(ev.status !== 'DRAFT' ? [{ id: 'clarifications', label: 'Clarifications', content: <ClarificationsPanel path={path} canManage={canManage} /> }] : []),
          {
            id: 'scenarios', label: `Award scenarios (${scenarios.length})`, content: (
              <ScenariosPanel event={ev} scenarios={scenarios} canAward={canManage && evaluating}
                onAward={(id) => { setAwardScenario(id); setDialog('award'); }} />
            ),
          },
        ] : []}
      />
      {ev && evaluating && (
        <p className="mt-3 text-xs text-slate-500">
          Next: score the non-price criteria, optionally run another sealed round, then build scenarios and propose an award. See also the{' '}
          <Link className="text-[#1A56DB] hover:underline" href="/pic/tasks">task inbox</Link> for approvals.
        </p>
      )}
      {ev && dialog === 'score' && <ScoreDialog event={ev} matrix={bids.data ?? []} onClose={() => setDialog(null)} />}
      {ev && dialog === 'round' && <RoundDialog event={ev} onClose={() => setDialog(null)} />}
      {ev && dialog === 'award' && <AwardDialog event={ev} scenarios={scenarios} matrix={bids.data} initial={awardScenario} onClose={() => setDialog(null)} />}
      {ev && dialog === 'cancel' && <CancelEventDialog event={ev} onClose={() => setDialog(null)} />}
    </>
  );
}

function pctStr(v: string | number | undefined) {
  return v === undefined || v === null ? '–' : `${Math.round(Number(v) * 100)}%`;
}
