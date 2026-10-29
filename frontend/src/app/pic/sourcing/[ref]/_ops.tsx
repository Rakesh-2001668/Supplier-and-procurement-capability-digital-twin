'use client';

import { useEffect, useState } from 'react';
import { Button, Dialog, Empty, Field, Input, Kpi, Loading, ProblemBox, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, inr, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

// ---------------------------------------------------------------- shapes (GET …/clarifications, GET …/auction)
type Clarification = { seq: number; kind: 'QUESTION' | 'NOTICE'; question: string; answer: string | null; status: string; askedAt: string;
  answeredAt: string | null; askedBy?: { code: string; name: string } | null; mine?: boolean };
type Board = { event: string; status: string; questionsCloseAt: string; open: boolean; openQuestions?: number; items: Clarification[] };
export type AuctionSettings = { minDecrementPct: string; extensionMinutes: number; triggerMinutes: number; showRank: boolean; showBestPrice: boolean;
  paymentTermsDays?: number | null; leadTimeDays?: number | null };
type LadderRow = { rank: number; supplier: string; name: string | null; priceMinor: number; submittedAt: string; bids: number };
type AuctionBidRow = { id: string; supplier?: string; priceMinor: number; rankAtSubmit?: number; submittedAt: string; extendedClose: boolean };
export type AuctionView = {
  event: string; status: string; round: number; live: boolean; serverTime: string; startsAt: string | null; scheduledCloseAt: string | null;
  endsAt: string | null; secondsLeft: number; extensions: number; bidders: number; settings: AuctionSettings; ruleSet: string | null;
  ladder?: LadderRow[]; bids?: AuctionBidRow[]; bestPriceMinor?: number | null; baselineMinor?: number | null; savingsVsBaselinePct?: string | null;
  invited?: number; myBids?: AuctionBidRow[]; myRank?: number | null; myLastPriceMinor?: number | null; nextMaxPriceMinor?: number | null;
};

export function formatLeft(seconds: number) {
  if (seconds <= 0) return 'ended';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}:${String(s).padStart(2, '0')}`;
}

/** Seconds left, counting down locally between 3-second polls. */
export function useCountdown(view: AuctionView | undefined, updatedAt: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (!view || !view.live) return 0;
  return Math.max(0, Math.round(view.secondsLeft - (now - updatedAt) / 1000));
}

// ---------------------------------------------------------------- F3-03 clarification board (buyer side)
export function ClarificationsPanel({ path, canManage }: { path: string; canManage: boolean }) {
  const { data, isLoading, error } = useApi<Board>(`${path}/clarifications`, { refetchInterval: 30000 });
  const [answering, setAnswering] = useState<Clarification | null>(null);
  const [notice, setNotice] = useState('');
  const publish = useCommand(() => api.post(`${path}/clarifications`, { text: notice.trim() }), {
    success: 'Notice published to all invited suppliers', onSuccess: () => setNotice('') });
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data) return null;
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        Invited suppliers ask questions until {dateTime(data.questionsCloseAt)}{data.open ? '' : ' (closed)'}. Answers and notices are published to every invitee;
        the asking supplier is never disclosed to the others. {data.openQuestions ? <span className="font-semibold text-amber-700">{data.openQuestions} open question(s).</span> : null}
      </p>
      {!data.items.length ? <Empty title="No questions or notices yet" /> : (
        <ul className="space-y-3">
          {data.items.map((c) => (
            <li key={c.seq} className="rounded-lg border border-slate-200 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-slate-500">#{c.seq}</span>
                <StatusChip status={c.kind === 'NOTICE' ? 'NOTICE' : c.status} />
                <span className="text-xs text-slate-500">{c.kind === 'NOTICE' ? 'Notice from Axion' : c.askedBy ? `asked by ${c.askedBy.name} (${c.askedBy.code})` : ''} · {dateTime(c.askedAt)}</span>
              </div>
              <p className="mt-1 text-sm text-slate-900">{c.question}</p>
              {c.answer && <p className="mt-1 rounded bg-emerald-50 px-2 py-1 text-sm text-emerald-900"><span className="font-semibold">Answer:</span> {c.answer} <span className="text-xs text-emerald-700">· {dateTime(c.answeredAt)}</span></p>}
              {canManage && c.status === 'OPEN' && <div className="mt-2"><Button variant="primary" onClick={() => setAnswering(c)}>Answer to all invitees</Button></div>}
            </li>
          ))}
        </ul>
      )}
      {canManage && !['DRAFT', 'CANCELLED', 'AWARDED'].includes(data.status) && (
        <div className="rounded-lg border border-slate-200 p-3">
          <Field label="Publish a notice to all invitees">{(id) => <Textarea id={id} value={notice} onChange={(e) => setNotice(e.target.value)}
            placeholder="e.g. Drawing revision C applies; site visit on …" />}</Field>
          <div className="mt-2 flex justify-end"><Button disabled={notice.trim().length < 3} busy={publish.isPending} onClick={() => publish.mutate()}>Publish notice</Button></div>
        </div>
      )}
      {answering && <AnswerDialog path={path} item={answering} onClose={() => setAnswering(null)} />}
    </div>
  );
}

function AnswerDialog({ path, item, onClose }: { path: string; item: Clarification; onClose: () => void }) {
  const [text, setText] = useState('');
  const answer = useCommand(() => api.post(`${path}/clarifications/${item.seq}/answer`, { answer: text.trim() }), {
    success: `Answer to #${item.seq} published to all invitees`, onSuccess: onClose });
  return (
    <Dialog open title={`Answer question #${item.seq}`} onClose={onClose}>
      <p className="mb-3 rounded bg-slate-50 p-2 text-sm">{item.question}</p>
      <Field label="Answer" hint="Published to every invited supplier without the asker's name">{(id) => <Textarea id={id} value={text} onChange={(e) => setText(e.target.value)} />}</Field>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={text.trim().length < 2} busy={answer.isPending} onClick={() => answer.mutate()}>Publish answer</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- SRC-04 live auction (buyer side)
export function AuctionPanel({ path, status, canManage }: { path: string; status: string; canManage: boolean }) {
  const live = status === 'OPEN';
  const query = useApi<AuctionView>(`${path}/auction`, { refetchInterval: live ? 3000 : undefined });
  const left = useCountdown(query.data, query.dataUpdatedAt);
  const [editing, setEditing] = useState(false);
  if (query.isLoading) return <Loading />;
  if (query.error) return <ProblemBox error={query.error} />;
  const a = query.data;
  if (!a) return null;
  const s = a.settings;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label={a.live ? 'Time left' : 'Auction'} value={a.live ? formatLeft(left) : label(a.status)} tone={a.live && left < 120 ? 'warn' : 'default'}
          hint={a.endsAt ? `ends ${dateTime(a.endsAt)}` : undefined} />
        <Kpi label="Best price / unit" value={inr(a.bestPriceMinor)} tone="good"
          hint={a.savingsVsBaselinePct ? `${a.savingsVsBaselinePct}% below baseline ${inr(a.baselineMinor)}` : a.baselineMinor ? `baseline ${inr(a.baselineMinor)}` : undefined} />
        <Kpi label="Bidders" value={`${a.bidders} / ${a.invited ?? '–'}`} hint={`${a.bids?.length ?? 0} bid(s)`} />
        <Kpi label="Soft-close extensions" value={a.extensions} hint={a.scheduledCloseAt ? `scheduled close ${dateTime(a.scheduledCloseAt)}` : undefined} tone={a.extensions ? 'warn' : 'default'} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
        <p>
          Each new bid must be ≥ {s.minDecrementPct}% below the supplier&apos;s own last bid. A bid in the last {s.triggerMinutes} min extends the end by {s.extensionMinutes} min.
          Suppliers see {s.showRank ? 'their rank' : 'no rank'}{s.showBestPrice ? ' and the best price' : ', not the best price'}.
          {s.paymentTermsDays != null || s.leadTimeDays != null ? ` Fixed terms: ${s.paymentTermsDays ?? 'supplier'} days payment, ${s.leadTimeDays ?? 'twin'} days lead time.` : ''}
          {a.ruleSet && <span className="ml-1 font-mono text-[11px] text-slate-400">{a.ruleSet}</span>}
        </p>
        {canManage && status === 'DRAFT' && <Button onClick={() => setEditing(true)}>Auction settings</Button>}
      </div>
      {a.live && <p className="text-xs text-slate-500" aria-live="polite">Live – refreshing every 3 seconds.</p>}
      {!a.live && ['UNDER_EVALUATION', 'AWARD_PENDING', 'AWARDED'].includes(status) && (
        <p className="text-sm text-slate-600">The auction has ended; each supplier&apos;s last price became a bid in the evaluation matrix (Bids &amp; evaluation tab).</p>
      )}
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Ladder</h3>
        {!a.ladder?.length ? <Empty title={status === 'DRAFT' ? 'Bidding starts when the event is published' : 'No bids yet'} /> : (
          <table className="min-w-full divide-y divide-slate-200 rounded-lg border border-slate-200 text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr><th className="px-3 py-2">Rank</th><th className="px-3 py-2">Supplier</th><th className="px-3 py-2 text-right">Last price</th>
                <th className="px-3 py-2 text-right">vs best</th><th className="px-3 py-2 text-right">Bids</th><th className="px-3 py-2">Last bid</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {a.ladder.map((r) => (
                <tr key={r.supplier} className={r.rank === 1 ? 'bg-emerald-50/50' : ''}>
                  <td className="px-3 py-2 font-semibold">{r.rank}</td>
                  <td className="px-3 py-2">{r.name} <span className="text-xs text-slate-500">({r.supplier})</span></td>
                  <td className="px-3 py-2 text-right tabular-nums">{inr(r.priceMinor)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-600">{a.bestPriceMinor ? `+${(((r.priceMinor - a.bestPriceMinor) / a.bestPriceMinor) * 100).toFixed(2)}%` : '–'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.bids}</td>
                  <td className="px-3 py-2">{dateTime(r.submittedAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {!!a.bids?.length && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Bid ledger (append-only)</h3>
          <ul className="max-h-64 space-y-1 overflow-y-auto text-sm">
            {a.bids.map((b) => (
              <li key={b.id} className="flex flex-wrap gap-x-3 border-b border-slate-100 py-1">
                <span className="w-40 text-slate-500">{dateTime(b.submittedAt)}</span>
                <span className="w-20 font-medium">{b.supplier}</span>
                <span className="w-28 text-right tabular-nums">{inr(b.priceMinor)}</span>
                <span className="text-slate-500">rank {b.rankAtSubmit} at submit</span>
                {b.extendedClose && <span className="font-medium text-amber-700">extended the close</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {editing && <AuctionSettingsDialog path={path} settings={s} onClose={() => setEditing(false)} />}
    </div>
  );
}

function AuctionSettingsDialog({ path, settings, onClose }: { path: string; settings: AuctionSettings; onClose: () => void }) {
  const [draft, setDraft] = useState({
    minDecrementPct: String(settings.minDecrementPct ?? ''), extensionMinutes: String(settings.extensionMinutes ?? ''),
    triggerMinutes: String(settings.triggerMinutes ?? ''), showRank: !!settings.showRank, showBestPrice: !!settings.showBestPrice,
    paymentTermsDays: settings.paymentTermsDays != null ? String(settings.paymentTermsDays) : '', leadTimeDays: settings.leadTimeDays != null ? String(settings.leadTimeDays) : '',
  });
  const save = useCommand(() => api.put(`${path}/auction`, {
    minDecrementPct: draft.minDecrementPct, extensionMinutes: Number(draft.extensionMinutes), triggerMinutes: Number(draft.triggerMinutes),
    showRank: draft.showRank, showBestPrice: draft.showBestPrice,
    ...(draft.paymentTermsDays !== '' ? { paymentTermsDays: Number(draft.paymentTermsDays) } : {}),
    ...(draft.leadTimeDays !== '' ? { leadTimeDays: Number(draft.leadTimeDays) } : {}),
  }), { success: 'Auction settings saved – they are frozen when the event is published', onSuccess: onClose });
  const set = (patch: Partial<typeof draft>) => setDraft((d) => ({ ...d, ...patch }));
  return (
    <Dialog open title="Reverse auction settings" onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">Defaults come from rule AUCTION; changes here apply to this event only.</p>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Minimum decrement (%)">{(id) => <Input id={id} type="number" min="0" max="49" step="0.1" value={draft.minDecrementPct} onChange={(e) => set({ minDecrementPct: e.target.value })} />}</Field>
        <Field label="Soft-close trigger (min)">{(id) => <Input id={id} type="number" min="0" value={draft.triggerMinutes} onChange={(e) => set({ triggerMinutes: e.target.value })} />}</Field>
        <Field label="Extension (min)">{(id) => <Input id={id} type="number" min="0" value={draft.extensionMinutes} onChange={(e) => set({ extensionMinutes: e.target.value })} />}</Field>
        <Field label="Fixed payment terms (days)" hint="Empty: supplier master terms">{(id) => <Input id={id} type="number" min="0" value={draft.paymentTermsDays} onChange={(e) => set({ paymentTermsDays: e.target.value })} />}</Field>
        <Field label="Fixed lead time (days)" hint="Empty: supplier twin lead time">{(id) => <Input id={id} type="number" min="0" value={draft.leadTimeDays} onChange={(e) => set({ leadTimeDays: e.target.value })} />}</Field>
      </div>
      <div className="mt-3 space-y-1 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" className="h-4 w-4" checked={draft.showRank} onChange={(e) => set({ showRank: e.target.checked })} /> Suppliers see their rank</label>
        <label className="flex items-center gap-2"><input type="checkbox" className="h-4 w-4" checked={draft.showBestPrice} onChange={(e) => set({ showBestPrice: e.target.checked })} /> Suppliers see the best price</label>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>Save settings</Button>
      </div>
    </Dialog>
  );
}
