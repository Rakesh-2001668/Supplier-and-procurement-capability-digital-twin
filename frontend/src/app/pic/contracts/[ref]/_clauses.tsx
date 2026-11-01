'use client';

import { useState } from 'react';
import { Button, Dialog, Empty, Field, Loading, ProblemBox, Select, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, inr, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

export type PendingRedline = { clause: string; proposedText: string | null; proposedPosition: string | null; originalText: string | null;
  originalPosition: string | null; by: string; at: string };
type ClauseItem = { clause: string; title: string; position: string; risk: number; textDeviates: boolean; deviation: boolean; fallback: string | null;
  suggestedPosition: string | null; text: string; standardText: string | null; pendingRedline: PendingRedline | null };
type ClauseReview = { contract: string; status: string; ruleSet: string; risk: number; riskBand: 'LOW' | 'MEDIUM' | 'HIGH'; deviations: number; pendingReview: string[];
  clauses: ClauseItem[]; approval: { chain: string[]; aboveThresholdMinor: number; valueMinor: number; reason: string } };

const POSITIONS = ['STANDARD', 'FALLBACK', 'NON_STANDARD'];
const BAND_TONE: Record<string, string> = { LOW: 'text-emerald-700', MEDIUM: 'text-amber-700', HIGH: 'text-red-700' };

export function PositionChip({ position }: { position: string }) {
  const tone = position === 'STANDARD' ? 'bg-emerald-50 text-emerald-800 ring-emerald-200' : position === 'FALLBACK' ? 'bg-amber-50 text-amber-800 ring-amber-200' : 'bg-red-50 text-red-800 ring-red-200';
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ring-1 ring-inset ${tone}`}>{position.replace(/_/g, ' ')}</span>;
}

/** CLM-02 Clause review and redline: each clause against the playbook (standard wording, deviation, risk score, fallback suggestion), the supplier
 * redlines waiting for review and the approval route the contract takes now. The contract manager proposes redlines while the contract is in negotiation. */
export function ClauseReviewTab({ contractNumber, status, canManage, onReview }: { contractNumber: string; status: string; canManage: boolean;
  onReview: (redline: PendingRedline) => void }) {
  const path = `/contracts/${encodeURIComponent(contractNumber)}`;
  const { data, isLoading, error } = useApi<ClauseReview>(`${path}/clause-review`);
  const [editing, setEditing] = useState<ClauseItem | null>(null);
  const negotiating = status === 'IN_NEGOTIATION';
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data) return null;
  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-slate-50 p-3 text-sm">
        <p>
          Contract risk <span className={`font-semibold ${BAND_TONE[data.riskBand]}`}>{data.risk}/100 ({data.riskBand.toLowerCase()})</span>
          {' · '}{data.deviations ? `${data.deviations} clause(s) deviate from the playbook` : 'every clause is on the playbook wording'}
          {' · '}playbook <span className="font-mono text-xs">{data.ruleSet}</span>
        </p>
        <p className="mt-1 text-slate-700">
          Approval route: <span className="font-semibold">{data.approval.chain.map(label).join(' → ')}</span>
          {' '}({data.approval.reason}; value {inr(data.approval.valueMinor)}, legal and finance from {inr(data.approval.aboveThresholdMinor)} or any non-standard clause).
        </p>
      </div>
      {data.pendingReview.length > 0 && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {data.pendingReview.length} supplier redline(s) wait for review ({data.pendingReview.join(', ')}). The contract cannot be submitted until each is accepted with a
          playbook position or restored.
        </p>
      )}
      {data.clauses.length === 0 ? <Empty title="No clauses" /> : (
        <ul className="space-y-3">
          {data.clauses.map((x) => (
            <li key={x.clause} className={`rounded-lg border p-3 ${x.pendingRedline ? 'border-amber-300 bg-amber-50/40' : x.deviation ? 'border-red-200' : 'border-slate-200'}`}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-slate-500">{x.clause}</span>
                <span className="text-sm font-semibold">{x.title}</span>
                <PositionChip position={x.position} />
                <span className="text-xs text-slate-600">risk {x.risk}</span>
                {x.textDeviates && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-semibold text-amber-900">wording differs from the library</span>}
                {x.pendingRedline && <span className="text-xs font-semibold text-amber-800">supplier redline · {x.pendingRedline.by} · {dateTime(x.pendingRedline.at)}</span>}
                <span className="ml-auto flex gap-2">
                  {x.pendingRedline && canManage && negotiating && <Button onClick={() => onReview(x.pendingRedline as PendingRedline)}>Review redline</Button>}
                  {canManage && negotiating && <Button onClick={() => setEditing(x)}>Propose redline</Button>}
                </span>
              </div>
              <p className="mt-1 text-sm text-slate-700">{x.text}</p>
              {x.deviation && x.standardText && x.textDeviates && (
                <p className="mt-2 rounded bg-white p-2 text-xs text-slate-600"><span className="font-semibold uppercase text-slate-500">Playbook standard wording</span><br />{x.standardText}</p>
              )}
              {x.deviation && x.fallback && (
                <p className="mt-2 text-xs text-slate-700"><span className="font-semibold uppercase text-slate-500">Fallback suggestion</span>{' '}
                  {x.fallback}{x.suggestedPosition ? <> – negotiating to this is a <PositionChip position={x.suggestedPosition} /> position</> : null}</p>
              )}
              {x.pendingRedline?.originalText && (
                <p className="mt-2 rounded bg-white p-2 text-xs text-slate-600"><span className="font-semibold uppercase text-slate-500">Text the supplier replaced</span><br />{x.pendingRedline.originalText}</p>
              )}
            </li>
          ))}
        </ul>
      )}
      {editing && <RedlineDialog contractNumber={contractNumber} clause={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function RedlineDialog({ contractNumber, clause, onClose }: { contractNumber: string; clause: ClauseItem; onClose: () => void }) {
  const [text, setText] = useState(clause.text);
  const [position, setPosition] = useState(clause.position);
  const go = useCommand(() => api.post(`/contracts/${encodeURIComponent(contractNumber)}/redlines`, { clause: clause.clause, text: text.trim(), position }), {
    success: `Redline on ${clause.clause} recorded`, onSuccess: onClose });
  return (
    <Dialog open title={`Redline · ${clause.clause} ${clause.title}`} onClose={onClose}>
      <div className="space-y-3 text-sm">
        <Field label="Clause text">{(id) => <Textarea id={id} rows={6} value={text} onChange={(e) => setText(e.target.value)} />}</Field>
        <Field label="Position against the playbook" hint="Non-standard routes the contract approval through Legal; a reworded clause should not stay on Standard">
          {(id) => <Select id={id} value={position} onChange={(e) => setPosition(e.target.value)} options={POSITIONS.map((p) => ({ value: p, label: label(p) }))} />}
        </Field>
        {clause.fallback && <p className="text-xs text-slate-600">Playbook fallback: {clause.fallback}</p>}
        <ProblemBox error={go.error} />
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!text.trim() || text.trim() === clause.text} busy={go.isPending} onClick={() => go.mutate()}>Record redline</Button>
      </div>
    </Dialog>
  );
}
