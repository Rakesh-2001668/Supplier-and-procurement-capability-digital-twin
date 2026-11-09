'use client';

// Award decisions with their authority band and exceptions, regret letters, the hand-off view, the event history and cloning.
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Button, Card, Dialog, Empty, Field, Input, Loading, ProblemBox, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, inr, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { toLocalInput } from './_parts';
import type { AwardDecision, Scenario, SourcingEvent } from './_parts';

type HistoryEntry = { seq: number; at: string; actor: string | null; action: string; reason: string | null; ruleSet: string | null; before: Record<string, unknown> | null; after: Record<string, unknown> | null; hash: string };
type Handoff = {
  event: string; status: string;
  decisions: { status: string; valueMinor: number; exceptions: { code: string; detail: string }[]; authority: { valueMinor: number; chain: string[]; bandChain: string[]; approvalAboveMinor: number; rule: string } | null; regretSentAt: string | null }[];
  contracts: { number: string; supplier: string; status: string; validFrom: string; validTo: string; targetValueMinor: number | null; pricesPublished: number; poReleaseEligible: boolean; blockedBecause: string | null }[];
  quotaArrangements: { material: string; plant: string; validFrom: string; validTo: string; suppliers: { supplier: string; sharePct: string; allocatedQty: string }[] }[];
  sourceListEntries: { material: string; plant: string; supplier: string; fixed: boolean; validFrom: string; validTo: string }[];
};

// ---------------------------------------------------------------- award decisions
export function AwardPanel({ event, scenarios }: { event: SourcingEvent; scenarios: Scenario[] }) {
  if (!event.awardDecisions.length) return <Empty title="No award proposed yet" hint="After scoring and building scenarios, propose an award. Its approval chain depends on the annual value (rule AWARD-APPROVAL)." />;
  return (
    <ul className="space-y-3" aria-label="Award decisions">
      {event.awardDecisions.map((d) => <DecisionCard key={d.id} d={d} kind={scenarios.find((s) => s.id === d.scenario_id)?.kind} />)}
    </ul>
  );
}

function DecisionCard({ d, kind }: { d: AwardDecision; kind?: string }) {
  const a = d.authority;
  const ex = d.exceptions ?? [];
  return (
    <li className="rounded-lg border border-slate-200 p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <StatusChip status={d.status} />
        <span className="font-medium">{label(kind ?? 'scenario')}</span>
        <span className="text-slate-600">· annual value {inr(d.annual_value_minor)} · {dateTime(d.created_at)}</span>
        <span className="font-mono text-[11px] text-slate-400">{d.rule_set_version}</span>
      </div>
      {a && (
        <div className="mt-2 rounded bg-slate-50 p-2" aria-label="Authority band">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Authority band</p>
          <p>
            Value {inr(a.valueMinor)} against the approval threshold {inr(a.approvalAboveMinor)} (rule {a.rule}). Approval chain:{' '}
            {a.chain.length ? a.chain.map(label).join(' → ') : 'no approver needed'}
            {a.bandChain.join() !== a.chain.join() && a.bandChain.length ? ` (by value alone: ${a.bandChain.map(label).join(' → ')})` : ''}.
          </p>
        </div>
      )}
      {ex.length > 0 && (
        <div className="mt-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Exceptions</p>
          <ul className="mt-1 space-y-1">{ex.map((e) => <li key={e.code}><span className="rounded bg-amber-50 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-amber-800 ring-1 ring-inset ring-amber-200">{e.code}</span> <span className="text-slate-700">{e.detail}</span>
            {e.override && (
              <p className="mt-1 rounded bg-red-50 px-2 py-1 text-xs text-red-900" aria-label="Expired-offer override">
                Expired offer overridden by {e.override.byName ?? e.override.byEmail ?? 'the proposer'}{e.override.at ? ` on ${dateTime(e.override.at)}` : ''}:
                {' '}{e.override.bids.map((b) => `${b.supplier} (valid until ${date(b.validUntil)})`).join(', ')}. Reason: “{e.override.reason}”
              </p>
            )}
          </li>)}</ul>
        </div>
      )}
      {d.rationale && <p className="mt-2 text-slate-700"><span className="font-semibold">Rationale:</span> {d.rationale}</p>}
      {d.conflict_declarations?.map((c) => <p key={c.user} className="mt-1 text-xs text-slate-500">Conflict declaration by {c.user}: “{c.declaration}”</p>)}
      <p className="mt-1 text-xs text-slate-500">{d.regret_sent_at ? `Regret letters sent ${dateTime(d.regret_sent_at)}.` : d.status === 'APPROVED' ? 'No regret letters recorded.' : 'Regret letters are sent when the award is approved.'}</p>
    </li>
  );
}

// ---------------------------------------------------------------- hand-off
export function HandoffPanel({ event, path, canManage }: { event: SourcingEvent; path: string; canManage: boolean }) {
  const { data, isLoading, error } = useApi<Handoff>(`${path}/handoff`);
  const history = useApi<HistoryEntry[]>(canManage && event.status === 'AWARDED' ? `${path}/history` : null);
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data) return null;
  const notified = (history.data ?? []).filter((h) => h.action === 'AWARD_NOTIFIED').map((h) => h.after).at(-1);
  const regret = (notified?.regretLetters as string[] | undefined) ?? [];
  if (!data.contracts.length && event.status !== 'AWARDED') {
    return <Empty title="Nothing handed off yet" hint="When the award is approved, a contract draft is created per awarded supplier, unsuccessful bidders receive a regret letter, and the savings initiative moves to Negotiated." />;
  }
  return (
    <div className="space-y-5">
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Contracts born from the award and purchase-order release</h3>
        {!data.contracts.length ? <p className="text-sm text-slate-600">No contract exists yet.</p> : (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <caption className="sr-only">Contracts created from the award and whether a purchase order can be released</caption>
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr>
                <th scope="col" className="px-3 py-2 text-left">Contract</th><th scope="col" className="px-3 py-2 text-left">Supplier</th><th scope="col" className="px-3 py-2 text-left">Status</th>
                <th scope="col" className="px-3 py-2 text-left">Valid</th><th scope="col" className="px-3 py-2 text-right">Target value</th><th scope="col" className="px-3 py-2 text-right">Prices published</th>
                <th scope="col" className="px-3 py-2 text-left">PO release</th></tr></thead>
              <tbody className="divide-y divide-slate-100 bg-white align-top">
                {data.contracts.map((c) => (
                  <tr key={c.number}>
                    <td className="px-3 py-2"><Link href={`/pic/contracts/${encodeURIComponent(c.number)}`} className="font-medium text-[#1A56DB] hover:underline">{c.number}</Link></td>
                    <td className="px-3 py-2">{c.supplier}</td><td className="px-3 py-2"><StatusChip status={c.status} /></td>
                    <td className="px-3 py-2">{date(c.validFrom)} – {date(c.validTo)}</td><td className="px-3 py-2 text-right tabular-nums">{inr(c.targetValueMinor)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{c.pricesPublished}</td>
                    <td className="px-3 py-2">{c.poReleaseEligible ? <StatusChip status="READY" /> : <span><StatusChip status="BLOCKED" /> <span className="text-xs text-slate-600">{c.blockedBecause}</span></span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Quota arrangements">
          {!data.quotaArrangements.length ? <p className="text-sm text-slate-600">None yet: created when a split award&apos;s contract is activated (shares as awarded, counters at zero).</p> : (
            <ul className="space-y-2 text-sm">{data.quotaArrangements.map((q, i) => (
              <li key={i}><span className="font-medium">{q.material}</span> · plant {q.plant} · {date(q.validFrom)} – {date(q.validTo)}
                <ul className="ml-4 list-disc">{q.suppliers.map((s) => <li key={s.supplier}>{s.supplier} {s.sharePct}% · allocated so far {s.allocatedQty}</li>)}</ul></li>
            ))}</ul>
          )}
        </Card>
        <Card title="Source list entries">
          {!data.sourceListEntries.length ? <p className="text-sm text-slate-600">None yet: written when the contract is activated.</p> : (
            <ul className="space-y-1 text-sm">{data.sourceListEntries.map((s, i) => <li key={i}>{s.material} · plant {s.plant} · {s.supplier}{s.fixed ? ' (fixed)' : ''} · {date(s.validFrom)} – {date(s.validTo)}</li>)}</ul>
          )}
        </Card>
      </div>
      <Card title="Regret letters">
        {data.decisions.some((d) => d.regretSentAt) ? (
          <div className="text-sm">
            <p>Sent {dateTime(data.decisions.find((d) => d.regretSentAt)?.regretSentAt)}{regret.length ? ` to ${regret.length} bidder(s): ${regret.join(', ')}` : ''}.</p>
            <p className="mt-1 text-xs text-slate-500">Each letter tells the bidder only what happened to its own bid (its own rank, or the disqualification reason); it never shows a competitor&apos;s name, price or score. Withdrawn bids get none. The bidder reads it as a notification in the supplier portal.</p>
          </div>
        ) : <p className="text-sm text-slate-600">No regret letter has been sent: they go out when the award is approved.</p>}
      </Card>
      {data.decisions.map((d, i) => d.exceptions?.length ? (
        <p key={i} className="text-xs text-slate-500">Decision {i + 1} ({label(d.status)}) carried: {d.exceptions.map((e) => e.code).join(', ')}.</p>
      ) : null)}
    </div>
  );
}

// ---------------------------------------------------------------- history (the event's audit trail)
export function HistoryPanel({ path }: { path: string }) {
  const { data, isLoading, error } = useApi<HistoryEntry[]>(`${path}/history`);
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data?.length) return <Empty title="No history yet" />;
  return (
    <div>
      <p className="mb-2 text-sm text-slate-600">Every change of the event, oldest first, with the rule versions it ran under. The hash chains each entry to the one before. Bid contents are never in it.</p>
      <ol className="space-y-1 text-sm" aria-label="Event history">
        {data.map((h) => (
          <li key={h.seq} className="grid gap-x-3 border-b border-slate-100 py-1.5 md:grid-cols-[10rem_14rem_1fr]">
            <span className="text-xs text-slate-500">{dateTime(h.at)}</span>
            <span><span className="font-mono text-xs font-semibold">{h.action}</span> <span className="text-slate-600">{h.actor ?? 'system'}</span></span>
            <span className="min-w-0 break-words text-slate-700">
              {h.reason ?? ''}
              {h.after && Object.keys(h.after).length > 0 && <span className="ml-1 font-mono text-[11px] text-slate-500">{JSON.stringify(h.after).slice(0, 220)}</span>}
              {h.ruleSet && <span className="ml-1 font-mono text-[11px] text-slate-400">{h.ruleSet}</span>}
              <span className="ml-1 font-mono text-[10px] text-slate-300" title={h.hash}>#{h.seq} {h.hash.slice(0, 8)}</span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

// ---------------------------------------------------------------- clone
export function CloneDialog({ event, onClose }: { event: SourcingEvent; onClose: () => void }) {
  const router = useRouter();
  const [closeAt, setCloseAt] = useState(() => toLocalInput(new Date(Date.now() + 7 * 864e5)));
  const [title, setTitle] = useState(`${event.title} (re-run)`);
  const [result, setResult] = useState<{ event: string; clonedFrom: string; invitees: string[]; droppedInvitees: { supplier: string; status: string }[] } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);
  const when = new Date(closeAt);
  const ok = !Number.isNaN(when.getTime()) && when.getTime() > now && title.trim().length > 0;
  const clone = useCommand(() => api.post<NonNullable<typeof result>>(`/sourcing/events/${encodeURIComponent(event.number)}/clone`, { close_at: when.toISOString(), title: title.trim() }),
    { success: (r) => `${r.event} created as a draft from ${r.clonedFrom}`, onSuccess: setResult });
  return (
    <Dialog open title={`Clone ${event.number}`} onClose={onClose}>
      {result ? (
        <div className="space-y-3 text-sm" role="status">
          <p><span className="font-semibold">{result.event}</span> is a draft copied from {result.clonedFrom}: criteria, constraints, TCO parameters and the eligible invitees ({result.invitees.join(', ')}).</p>
          {result.droppedInvitees.length > 0 && <p className="text-amber-800">Dropped (no longer eligible for the category): {result.droppedInvitees.map((d) => `${d.supplier} (${label(d.status)})`).join(', ')}.</p>}
          <div className="flex justify-end gap-2"><Button onClick={onClose}>Stay here</Button><Button variant="primary" onClick={() => router.push(`/pic/sourcing/${encodeURIComponent(result.event)}`)}>Open the draft</Button></div>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-700">A re-tender after a cancellation or the next round of a contract. The copy is always a draft; suppliers that lost their qualification are dropped and listed.</p>
          <Field label="Title" required>{(id) => <Input id={id} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />}</Field>
          <Field label="Close date-time" required>{(id) => <Input id={id} type="datetime-local" value={closeAt} onChange={(e) => setCloseAt(e.target.value)} />}</Field>
          <div className="flex justify-end gap-2"><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!ok} busy={clone.isPending} onClick={() => clone.mutate()}>Create draft copy</Button></div>
        </div>
      )}
    </Dialog>
  );
}
