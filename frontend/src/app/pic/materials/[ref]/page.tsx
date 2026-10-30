'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { AuditTrail, LineageView, ProcessPath } from '@/components/pic/object';
import { Button, Card, Dialog, Empty, Facts, Field, Loading, ProblemBox, StatusChip, Tabs, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

/** A duplicate candidate: an active material, or a material request still in flight (no material yet). */
type Candidate = {
  id: string; kind?: 'MATERIAL' | 'MATERIAL_REQUEST'; material: string | null; materialRequest?: string; status?: string;
  score: number; parts: Record<string, number>;
};
type MaterialRequest = {
  id: string; number: string; status: string; description: string; type: string; material_group: string; category: string; base_uom: string;
  valuation_class: string | null; hsn_code: string | null; mpn: string | null; attributes: Record<string, unknown>;
  source_pr_id: string | null; source_pr_line: number | null; duplicate_score: string | null; duplicate_candidates: Candidate[] | null;
  override_reason: string | null; material_id: string | null; merged_into_material_id: string | null; rule_set_version: string | null;
  requested_by: string; created_at: string; updated_at: string | null;
};
type Task = { id: string; name: string; kind: string; object_ref: string; status?: string; due_at: string | null };
type Me = { userId: string; roles: string[] };
type Material = { id: string; number: string; description: string };

const PART_LABEL: Record<string, string> = { description: 'Description', classification: 'Classification', mpn: 'MPN', attributes: 'Attributes' };
const pct = (v: number | string | null | undefined) => (v == null ? '–' : `${Math.round(Number(v) * 100)}%`);

export default function MaterialRequestPage() {
  const { ref } = useParams<{ ref: string }>();
  const { data: mr, isLoading, error } = useApi<MaterialRequest>(`/materials/requests/${encodeURIComponent(ref)}`);
  const tasks = useApi<Task[]>('/tasks');
  const me = useApi<Me>('/me');
  // The request carries material ids only; resolve created / merged material numbers from the master list.
  const materials = useApi<{ items: Material[] }>('/materials?limit=200');
  const [dialog, setDialog] = useState<'override' | null>(null);

  if (isLoading) return <Loading />;
  if (error || !mr) return <ProblemBox error={error} />;

  const stewardTask = (tasks.data ?? []).find((t) => t.kind === 'MDM_STEWARD' && t.object_ref === mr.number);
  const isSteward = !!me.data?.roles.includes('MDM_STEWARD');
  // The API lets the requester or a steward merge a blocked request, and only a steward merge one in stewardship.
  const isRequester = !!me.data && me.data.userId === mr.requested_by;
  const canMerge = (mr.status === 'DUPLICATE_BLOCKED' && (isSteward || isRequester)) || (mr.status === 'IN_STEWARDSHIP' && isSteward);
  const materialNo = (id: string | null) => (id ? materials.data?.items.find((m) => m.id === id)?.number ?? '…' : null);
  const candidates = mr.duplicate_candidates ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-xs uppercase tracking-wider text-slate-500">MDM-02 · Material request</p>
          <div className="mt-1 flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-[#0B1020]">{mr.number} <span className="text-base font-normal text-slate-500">{mr.description}</span></h1>
            <StatusChip status={mr.status} />
          </div>
        </div>
        {mr.status === 'DUPLICATE_BLOCKED' && isSteward && <Button onClick={() => setDialog('override')}>Steward override</Button>}
      </div>

      {mr.status === 'DUPLICATE_BLOCKED' && (
        <div role="status" className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p className="font-semibold">Blocked as a likely duplicate ({pct(mr.duplicate_score)} match with {candidates[0] ? candidateLabel(candidates[0]) : 'an existing material'}).</p>
          <p>Merge it into the existing material below, or a data steward can override the block with a reason and send it to stewardship.</p>
        </div>
      )}

      {stewardTask && <StewardDecision mr={mr} task={stewardTask} />}

      <Card>
        <Facts items={[
          ['Status', label(mr.status)], ['Duplicate score', pct(mr.duplicate_score)], ['Type', label(mr.type)], ['Base UoM', mr.base_uom],
          ['Material group', mr.material_group], ['Category', mr.category], ['HSN code', mr.hsn_code ?? '–'], ['MPN', mr.mpn ?? '–'],
          ['Valuation class', mr.valuation_class ?? '–'],
          ['Source requisition', mr.source_pr_id ? <Link className="text-[#1A56DB] hover:underline" href={`/pic/requisitions/${mr.source_pr_id}`}>line {mr.source_pr_line} →</Link> : '–'],
          ['Material created', materialNo(mr.material_id) ?? '–'], ['Merged into', materialNo(mr.merged_into_material_id) ?? '–'],
          ['Override reason', mr.override_reason ?? '–'], ['Rules', mr.rule_set_version ?? '–'], ['Requested', dateTime(mr.created_at)],
          ['Updated', dateTime(mr.updated_at)],
        ]} />
      </Card>

      <Card title="Duplicate check (MDM-01)">
        {!candidates.length ? <Empty title="No similar materials found" hint="The request goes straight to the data stewards." /> : (
          <ul className="space-y-3">
            {candidates.map((c) => <CandidateRow key={c.id} mr={mr} candidate={c} canMerge={canMerge} />)}
          </ul>
        )}
      </Card>

      <Card>
        <Tabs tabs={[
          { id: 'data', label: 'Requested data', content: (
            Object.keys(mr.attributes ?? {}).length ? (
              <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                {Object.entries(mr.attributes).map(([k, v]) => (
                  <div key={k}><dt className="text-xs text-slate-500">{k}</dt><dd className="font-medium">{String(v)}</dd></div>
                ))}
              </dl>
            ) : <Empty title="No attributes supplied" />
          ) },
          { id: 'process', label: 'Process', content: <ProcessPath type="MATERIAL_REQUEST" objectRef={mr.number} /> },
          { id: 'lineage', label: 'Lineage', content: <LineageView type="MATERIAL_REQUEST" objectRef={mr.number} /> },
          { id: 'audit', label: 'Audit', content: <AuditTrail type="MATERIAL_REQUEST" objectRef={mr.number} /> },
        ]} />
      </Card>

      {dialog === 'override' && <OverrideDialog mr={mr} onClose={() => setDialog(null)} />}
    </div>
  );
}

function candidateLabel(c: Candidate) {
  return c.material ?? `request ${c.materialRequest ?? ''}`;
}

function CandidateRow({ mr, candidate, canMerge }: { mr: MaterialRequest; candidate: Candidate; canMerge: boolean }) {
  const merge = useCommand(() => api.post(`/materials/requests/${mr.number}/merge`, { material: candidate.material }),
    { success: `${mr.number} merged into ${candidate.material}` });
  const inFlight = candidate.kind === 'MATERIAL_REQUEST';
  return (
    <li className="rounded-lg border border-slate-200 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {inFlight ? (
            <Link className="font-semibold text-[#1A56DB] hover:underline" href={`/pic/materials/${candidate.materialRequest}`}>Request {candidate.materialRequest}</Link>
          ) : <span className="font-semibold">{candidate.material}</span>}
          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-semibold tabular-nums">{pct(candidate.score)} match</span>
          {inFlight && <span className="text-xs text-slate-500">in flight ({label(candidate.status ?? '')}) — no material yet; merge once it is live</span>}
        </div>
        {canMerge && !inFlight && candidate.material && <Button busy={merge.isPending} onClick={() => merge.mutate()}>Merge into {candidate.material}</Button>}
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2 md:grid-cols-4">
        {Object.entries(candidate.parts).map(([part, score]) => (
          <div key={part}>
            <div className="flex justify-between text-xs"><span className="text-slate-600">{PART_LABEL[part] ?? label(part)}</span><span className="font-medium tabular-nums">{pct(score)}</span></div>
            <div className="mt-1 h-1.5 rounded-full bg-slate-100" aria-hidden>
              <div className={`h-1.5 rounded-full ${score >= 0.9 ? 'bg-red-500' : score >= 0.6 ? 'bg-amber-500' : 'bg-slate-400'}`} style={{ width: `${Math.round(score * 100)}%` }} />
            </div>
          </div>
        ))}
      </div>
    </li>
  );
}

function StewardDecision({ mr, task }: { mr: MaterialRequest; task: Task }) {
  const [comment, setComment] = useState('');
  const decide = useCommand((decision: 'APPROVE' | 'REJECT') => api.post(`/materials/requests/${mr.number}/decision`, { decision, comment: comment.trim() || undefined }),
    { success: 'Steward decision recorded' });
  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50/40 p-4">
      <p className="text-sm font-semibold">{task.name}</p>
      <p className="text-xs text-slate-600">Steward decision (MDM-03) · due {dateTime(task.due_at)}. Approval creates the material and syncs it to ERP once every domain has approved.</p>
      <div className="mt-3 flex flex-col gap-2 md:flex-row md:items-end">
        <div className="md:flex-1">
          <Field label="Comment (required to reject)">{(id) => <Textarea id={id} value={comment} onChange={(e) => setComment(e.target.value)} />}</Field>
        </div>
        <div className="flex gap-2">
          <Button variant="primary" busy={decide.isPending} onClick={() => decide.mutate('APPROVE')}>Approve</Button>
          <Button variant="danger" busy={decide.isPending} disabled={!comment.trim()} onClick={() => decide.mutate('REJECT')}>Reject</Button>
        </div>
      </div>
    </div>
  );
}

function OverrideDialog({ mr, onClose }: { mr: MaterialRequest; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const override = useCommand(() => api.post(`/materials/requests/${mr.number}/override`, { reason: reason.trim() }),
    { success: `${mr.number} override recorded — sent to stewardship`, onSuccess: onClose });
  return (
    <Dialog open title={`Override duplicate block on ${mr.number}`} onClose={onClose}>
      <Field label="Reason *" hint="Explain why this is not a duplicate. The override is audited and the request goes to the data stewards.">{(id) => (
        <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />
      )}</Field>
      <div className="mt-3"><ProblemBox error={override.error} /></div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={override.isPending} disabled={!reason.trim()} onClick={() => override.mutate()}>Override block</Button>
      </div>
    </Dialog>
  );
}
