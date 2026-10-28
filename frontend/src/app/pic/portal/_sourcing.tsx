'use client';

// Supplier side of the clarification board (F3-03) and the live reverse auction (SRC-04).
import { useState } from 'react';
import { Button, Dialog, Empty, Field, Input, Kpi, Loading, ProblemBox, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, inr, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { AuctionView, formatLeft, useCountdown } from '../sourcing/[ref]/_ops';

type Clarification = { seq: number; kind: 'QUESTION' | 'NOTICE'; question: string; answer: string | null; status: string; askedAt: string;
  answeredAt: string | null; mine: boolean };
type Board = { event: string; status: string; questionsCloseAt: string; open: boolean; items: Clarification[] };

export function EventQaDialog({ number, onClose }: { number: string; onClose: () => void }) {
  const path = `/sourcing/events/${encodeURIComponent(number)}/clarifications`;
  const { data, isLoading, error } = useApi<Board>(path, { refetchInterval: 30000 });
  const [text, setText] = useState('');
  const ask = useCommand(() => api.post(path, { text: text.trim() }), { success: 'Question sent – the answer is shared with all invited suppliers',
    onSuccess: () => setText('') });
  const withdraw = useCommand((seq: number) => api.post(`${path}/${seq}/withdraw`), { success: 'Question withdrawn' });
  return (
    <Dialog open title={`${number} · Questions & answers`} onClose={onClose}>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : data && (
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            Ask the buyer about the requirement until {dateTime(data.questionsCloseAt)}. Answers are published to every invited supplier and never show who asked.
            You also see your own questions that are still open.
          </p>
          {!data.items.length ? <Empty title="No answers or notices yet" /> : (
            <ul className="max-h-80 space-y-2 overflow-y-auto">
              {data.items.map((c) => (
                <li key={c.seq} className="rounded-lg border border-slate-200 p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusChip status={c.kind === 'NOTICE' ? 'NOTICE' : c.status} />
                    {c.mine && <span className="text-xs font-medium text-[#1A56DB]">your question</span>}
                    <span className="text-xs text-slate-500">{dateTime(c.askedAt)}</span>
                  </div>
                  <p className="mt-1">{c.question}</p>
                  {c.answer && <p className="mt-1 rounded bg-emerald-50 px-2 py-1 text-emerald-900"><span className="font-semibold">Answer:</span> {c.answer}</p>}
                  {c.mine && c.status === 'OPEN' && (
                    <div className="mt-1"><Button variant="ghost" busy={withdraw.isPending} onClick={() => withdraw.mutate(c.seq)}>Withdraw</Button></div>
                  )}
                </li>
              ))}
            </ul>
          )}
          {data.open ? (
            <div>
              <Field label="Your question">{(id) => <Textarea id={id} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Is drawing revision C final?" />}</Field>
              <div className="mt-2 flex justify-end gap-2">
                <Button onClick={onClose}>Close</Button>
                <Button variant="primary" disabled={text.trim().length < 3} busy={ask.isPending} onClick={() => ask.mutate()}>Send question</Button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm text-slate-500">The question window is closed.</p>
              <Button onClick={onClose}>Close</Button>
            </div>
          )}
        </div>
      )}
    </Dialog>
  );
}

export function AuctionDialog({ number, onClose }: { number: string; onClose: () => void }) {
  const path = `/sourcing/events/${encodeURIComponent(number)}/auction`;
  const query = useApi<AuctionView>(path, { refetchInterval: 3000 });
  const left = useCountdown(query.data, query.dataUpdatedAt);
  const [price, setPrice] = useState('');
  const bid = useCommand(() => api.post<AuctionView>(`${path}/bids`, { priceMinor: rupeesToMinor(price) }), {
    success: (r) => (r.myRank ? `Bid placed – you are rank ${r.myRank}` : 'Bid placed'), onSuccess: () => setPrice('') });
  const a = query.data;
  const minor = price ? rupeesToMinor(price) : 0;
  const tooHigh = !!a?.nextMaxPriceMinor && minor > a.nextMaxPriceMinor;
  return (
    <Dialog open title={`${number} · Live reverse auction`} onClose={onClose}>
      {query.isLoading ? <Loading /> : query.error ? <ProblemBox error={query.error} /> : a && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <Kpi label="Time left" value={a.live ? formatLeft(left) : 'ended'} tone={a.live && left < 120 ? 'warn' : 'default'}
              hint={a.endsAt ? `ends ${dateTime(a.endsAt)}${a.extensions ? ` · extended ${a.extensions}×` : ''}` : undefined} />
            <Kpi label="Your rank" value={a.myRank ?? (a.settings.showRank ? '–' : 'hidden')} tone={a.myRank === 1 ? 'good' : 'default'}
              hint={a.bidders ? `${a.bidders} bidder(s)` : undefined} />
            <Kpi label="Your last bid" value={inr(a.myLastPriceMinor)} hint={a.settings.showBestPrice ? `best ${inr(a.bestPriceMinor)}` : 'best price not disclosed'} />
          </div>
          <p className="text-sm text-slate-600">
            Prices are per unit. Each bid must be at least {a.settings.minDecrementPct}% below your own last bid. A bid in the last {a.settings.triggerMinutes} minutes
            extends the auction by {a.settings.extensionMinutes} minutes. Your final price becomes your bid for evaluation at close.
          </p>
          {a.live ? (
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[200px] flex-1">
                <Field label="Your price per unit (₹)" hint={a.nextMaxPriceMinor ? `At most ${inr(a.nextMaxPriceMinor)}` : 'Your opening bid'}>
                  {(id) => <Input id={id} type="number" min="0" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} aria-invalid={tooHigh} />}
                </Field>
              </div>
              <Button variant="primary" disabled={!minor || minor <= 0 || tooHigh} busy={bid.isPending} onClick={() => bid.mutate()}>Place bid</Button>
            </div>
          ) : <p className="text-sm font-medium text-slate-700">{a.status === 'PUBLISHED' ? 'Bidding has not started.' : 'The auction has ended.'}</p>}
          {tooHigh && <p className="text-sm text-red-700">Your bid must be {inr(a.nextMaxPriceMinor)} or less.</p>}
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Your bids</h3>
            {!a.myBids?.length ? <p className="text-sm text-slate-500">No bids yet.</p> : (
              <ul className="max-h-48 space-y-1 overflow-y-auto text-sm">
                {a.myBids.map((b) => (
                  <li key={b.id} className="flex flex-wrap gap-x-3 border-b border-slate-100 py-1">
                    <span className="w-40 text-slate-500">{dateTime(b.submittedAt)}</span>
                    <span className="w-28 text-right font-medium tabular-nums">{inr(b.priceMinor)}</span>
                    {a.settings.showRank && <span className="text-slate-500">rank {b.rankAtSubmit} when placed</span>}
                    {b.extendedClose && <span className="text-amber-700">extended the close</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="flex justify-end"><Button onClick={onClose}>Close</Button></div>
        </div>
      )}
    </Dialog>
  );
}
