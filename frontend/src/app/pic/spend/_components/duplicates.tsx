'use client';

import Link from 'next/link';
import { useState } from 'react';
import { TaskPanel } from '@/components/pic/object';
import { Button, Card, Dialog, Empty, Field, Kpi, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { crore, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { period, SpendProblem } from './shared';

type Member = { code: string; name: string; spendMinor: number; parent: string | null };
type Cluster = { key: string; suppliers: Member[]; reason: string; reasons: string[]; score: number; status: string; survivor: string | null; proposal: string | null };
type Clusters = { clusters: Cluster[]; window: [string, string] };

const REASON_TEXT: Record<string, string> = { PAN: 'Same PAN', GSTIN: 'Same GSTIN', BANK: 'Same bank account' };

/** Supplier records that look like one legal entity: scan, propose a merge (a second steward approves it) or dismiss. Nothing is merged, blocked or deleted. */
export function DuplicatesTab() {
  const { data, isLoading, error } = useApi<Clusters>('/spend/duplicates');
  const [proposing, setProposing] = useState<Cluster | null>(null);
  const [dismissing, setDismissing] = useState<Cluster | null>(null);
  const scan = useCommand(() => api.post<{ new: number; known: number }>('/spend/duplicates/scan', {}), {
    success: (r) => `Scan stored: ${r.new} new cluster(s), ${r.known} already known`,
  });
  const clusters = data?.clusters ?? [];
  const total = clusters.reduce((s, c) => s + c.suppliers.reduce((a, m) => a + m.spendMinor, 0), 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-3xl text-sm text-slate-600">
          Clusters join records with the same PAN or GSTIN, the same bank account, or a near-identical legal name (digits must agree: “Plant 1” and “Plant 2” are different suppliers).
          A merge is proposed by one steward and approved by a <strong>second</strong> steward as a task: the proposer cannot approve it. Approval links the records to a corporate parent so the cube rolls them up;
          nothing is merged, blocked or deleted in the ERP.
        </p>
        <Button busy={scan.isPending} onClick={() => scan.mutate()}>Scan for duplicates</Button>
      </div>
      {scan.error && <ProblemBox error={scan.error} />}
      {isLoading ? <Loading /> : error ? <SpendProblem error={error} permission="spend:read or mdm:request" /> : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Clusters" value={clusters.length} hint={data ? `spend ${period(data.window[0])} – ${period(data.window[1])}` : undefined} />
            <Kpi label="Waiting for a decision" value={clusters.filter((c) => c.status === 'OPEN' || c.status === 'REJECTED').length} tone="warn" />
            <Kpi label="Merge proposed" value={clusters.filter((c) => c.status === 'PROPOSED').length} hint="second steward to approve" />
            <Kpi label="Spend in clusters" value={crore(total)} hint="last 12 months" />
          </div>
          {!clusters.length ? <Empty title="No duplicate clusters" hint="Run a scan after loading or changing the supplier master." /> : (
            <ul className="space-y-4" aria-label="Duplicate supplier clusters">
              {clusters.map((c) => {
                const open = c.status === 'OPEN' || c.status === 'REJECTED';
                return (
                  <li key={c.key}>
                    <Card title={<span className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-slate-500">{c.key.slice(0, 8)}</span>
                      <span>{c.reasons.length ? c.reasons.map((r) => REASON_TEXT[r] ?? label(r)).join(' · ') : c.reason}</span>
                      <span className="text-xs font-normal text-slate-500">score {c.score.toFixed(2)}</span>
                      <StatusChip status={c.status === 'PROPOSED' ? 'PENDING' : c.status} />
                    </span>} actions={open && (
                      <>
                        <Button variant="primary" onClick={() => setProposing(c)} aria-label={`Propose merge of cluster ${c.key.slice(0, 8)}`}>Propose merge</Button>
                        <Button onClick={() => setDismissing(c)} aria-label={`Dismiss cluster ${c.key.slice(0, 8)}`}>Not duplicates</Button>
                      </>
                    )}>
                      <ul className="divide-y divide-slate-100 text-sm">
                        {c.suppliers.map((m) => (
                          <li key={m.code} className="flex flex-wrap items-center justify-between gap-2 py-2 first:pt-0 last:pb-0">
                            <span><Link href={`/pic/suppliers/${encodeURIComponent(m.code)}`} className="font-mono text-xs font-medium text-[#1A56DB] hover:underline">{m.code}</Link> {m.name}
                              {c.survivor === m.code && <span className="ml-2 rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-semibold text-blue-800 ring-1 ring-inset ring-blue-200">survivor</span>}</span>
                            <span className="tabular-nums text-slate-700">{crore(m.spendMinor)}</span>
                          </li>
                        ))}
                      </ul>
                      {c.status === 'PROPOSED' && c.proposal && (
                        <div className="mt-4 space-y-2">
                          <p className="text-sm text-slate-700">Proposal <span className="font-mono font-semibold">{c.proposal}</span> keeps <span className="font-mono">{c.survivor}</span> as the survivor. A steward other than the proposer approves or rejects it:</p>
                          <TaskPanel objectRef={c.proposal} />
                          <p className="text-xs text-slate-500">If no decision form shows here, the proposal is waiting in the approval inbox of another steward (<Link href="/pic/tasks" className="font-medium text-[#1A56DB] hover:underline">open the inbox</Link>).</p>
                        </div>
                      )}
                    </Card>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
      {proposing && <ProposeDialog cluster={proposing} onClose={() => setProposing(null)} />}
      {dismissing && <DismissDialog cluster={dismissing} onClose={() => setDismissing(null)} />}
    </div>
  );
}

function ProposeDialog({ cluster, onClose }: { cluster: Cluster; onClose: () => void }) {
  const top = [...cluster.suppliers].sort((a, b) => b.spendMinor - a.spendMinor)[0];
  const [survivor, setSurvivor] = useState(top?.code ?? '');
  const [note, setNote] = useState('');
  const propose = useCommand(() => api.post<{ proposal_number: string }>(`/spend/duplicates/${cluster.key}/propose-merge`, { survivor, note: note.trim() }), {
    success: (r) => `Merge proposed as ${r.proposal_number}; a second steward must approve it`, onSuccess: onClose,
  });
  return (
    <Dialog open title="Propose a supplier merge" onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">The other records become part of the survivor’s group in spend reporting once a second steward approves. Nothing is changed in the ERP.</p>
      <div className="grid gap-3">
        <Field label="Survivor" required>{(id) => <Select id={id} value={survivor} onChange={(e) => setSurvivor(e.target.value)} options={cluster.suppliers.map((m) => ({ value: m.code, label: `${m.code} · ${m.name} · ${crore(m.spendMinor)}` }))} />}</Field>
        <Field label="Why these are one supplier" required hint="At least 5 characters">{(id, d) => <Textarea id={id} aria-describedby={d} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Same GSTIN and registered address; the old code was never blocked" />}</Field>
      </div>
      {propose.error && <div className="mt-3"><ProblemBox error={propose.error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!survivor || note.trim().length < 5} busy={propose.isPending} onClick={() => propose.mutate()}>Propose merge</Button>
      </div>
    </Dialog>
  );
}

function DismissDialog({ cluster, onClose }: { cluster: Cluster; onClose: () => void }) {
  const [note, setNote] = useState('');
  const dismiss = useCommand(() => api.post(`/spend/duplicates/${cluster.key}/dismiss`, { note: note.trim() }), { success: 'Cluster dismissed: it will not come back while its members stay the same', onSuccess: onClose });
  return (
    <Dialog open title="These are different suppliers" onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">{cluster.suppliers.map((m) => m.code).join(', ')}</p>
      <Field label="Why they are different entities" required hint="At least 5 characters">{(id, d) => <Textarea id={id} aria-describedby={d} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Separate legal entities with different GSTINs that share a group name" />}</Field>
      {dismiss.error && <div className="mt-3"><ProblemBox error={dismiss.error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={note.trim().length < 5} busy={dismiss.isPending} onClick={() => dismiss.mutate()}>Dismiss cluster</Button>
      </div>
    </Dialog>
  );
}
