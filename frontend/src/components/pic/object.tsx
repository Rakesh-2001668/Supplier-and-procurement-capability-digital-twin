'use client';

import Link from 'next/link';
import { ReactNode, useMemo, useState, useSyncExternalStore } from 'react';
import { api, readSessionUser } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { docHref, TYPE_LABEL } from '@/lib/pic/links';
import { Button, Card, Empty, Loading, ProblemBox, StatusChip, Tabs, Textarea } from './ui';

type Step = { step: string; name: string; lane: string; type: string; status: string; actor: string | null; outcome: string | null; at: string };
type ProcessHistory = { id: string; process: string; flow: string; name: string; status: string; currentStep: string; path: Step[];
  tasks: { id: string; name: string; role: string; status: string; decision: string | null; comment: string | null; completedAt: string | null }[] };
type Task = { id: string; name: string; kind: string; object_type: string; object_ref: string; candidate_role: string; due_at: string | null;
  escalation_level: number; evidence: Record<string, unknown> };

// ---------------------------------------------------------------- process path (live BPMN token position)
export function ProcessPath({ type, objectRef }: { type: string; objectRef: string }) {
  const { data, isLoading, error } = useApi<ProcessHistory[]>(`/documents/${type}/${encodeURIComponent(objectRef)}/process`);
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data?.length) return <Empty title="No workflow recorded for this document" />;
  return (
    <div className="space-y-6">
      {data.map((p) => (
        <div key={p.id}>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="rounded bg-[#0B1020] px-2 py-0.5 font-mono text-xs text-white">{p.flow}</span>
            <span className="text-sm font-semibold">{p.name}</span>
            <StatusChip status={p.status} />
          </div>
          <ol className="relative ml-3 border-l-2 border-slate-200">
            {p.path.map((s, i) => (
              <li key={`${s.step}-${i}`} className="mb-3 ml-5">
                <span className={`absolute -left-[9px] mt-1 flex h-4 w-4 items-center justify-center rounded-full ring-4 ring-white ${s.status === 'ACTIVE' ? 'bg-amber-400' : s.status === 'SKIPPED' ? 'bg-slate-300' : 'bg-emerald-500'}`} aria-hidden />
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-mono text-xs text-slate-500">{s.step}</span>
                  <span className="text-sm font-medium">{s.name}</span>
                  <span className="text-xs text-slate-500">· {s.lane}</span>
                  {s.status !== 'COMPLETED' && <StatusChip status={s.status === 'ACTIVE' ? 'ACTIVE_STEP' : s.status} />}
                </div>
                {s.outcome && <p className="text-sm text-slate-700">{s.outcome}</p>}
                <p className="text-xs text-slate-500">{s.actor} · {dateTime(s.at)}</p>
              </li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- lineage (P10)
export function LineageView({ type, objectRef }: { type: string; objectRef: string }) {
  const { data, isLoading, error } = useApi<{ nodes: { type: string; id: string; ref: string }[]; edges: { from: string; to: string; type: string; fromLine: number | null; toLine: number | null }[] }>(
    `/lineage/${type}/${encodeURIComponent(objectRef)}`);
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data?.edges.length) return <Empty title="No linked documents yet" />;
  const nodes = Object.fromEntries(data.nodes.map((n) => [n.ref, n]));
  return (
    <ul className="space-y-2">
      {data.edges.map((e, i) => (
        <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
          <DocLink node={nodes[e.from]} line={e.fromLine} />
          <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-600">{e.type.replace(/_/g, ' ')} →</span>
          <DocLink node={nodes[e.to]} line={e.toLine} />
        </li>
      ))}
    </ul>
  );
}

function DocLink({ node, line }: { node?: { type: string; id: string; ref: string }; line: number | null }) {
  if (!node) return null;
  const href = docHref(node.type, node.ref, node.id);
  const text = `${TYPE_LABEL[node.type] ?? label(node.type)} ${node.ref}${line ? ` / ${line}` : ''}`;
  return href ? <Link href={href} className="font-medium text-[#1A56DB] hover:underline">{text}</Link> : <span className="font-medium">{text}</span>;
}

// ---------------------------------------------------------------- audit trail
export function AuditTrail({ type, objectRef }: { type: string; objectRef: string }) {
  const { data, isLoading, error } = useApi<{ seq: number; action: string; actor: string; reason: string | null; before: unknown; after: unknown; ruleSetVersion: string | null; aiRef: string | null; ts: string; hash: string }[]>(
    `/audit/${type}/${encodeURIComponent(objectRef)}`);
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data?.length) return <Empty title="No audit events" />;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead><tr className="text-left text-xs uppercase tracking-wide text-slate-500">
          <th className="py-1 pr-4">When</th><th className="py-1 pr-4">Action</th><th className="py-1 pr-4">Actor</th><th className="py-1 pr-4">Detail</th><th className="py-1">Hash</th>
        </tr></thead>
        <tbody className="divide-y divide-slate-100">
          {data.map((e) => (
            <tr key={e.seq} className="align-top">
              <td className="whitespace-nowrap py-1.5 pr-4 text-slate-600">{dateTime(e.ts)}</td>
              <td className="py-1.5 pr-4 font-medium">{label(e.action)}</td>
              <td className="py-1.5 pr-4 text-slate-700">{e.actor}</td>
              <td className="py-1.5 pr-4 text-slate-700">
                {e.reason && <p>{e.reason}</p>}
                {e.after ? <p className="font-mono text-[11px] text-slate-500">{JSON.stringify(e.after).slice(0, 180)}</p> : null}
                {(e.ruleSetVersion || e.aiRef) && <p className="font-mono text-[11px] text-slate-400">{[e.ruleSetVersion, e.aiRef].filter(Boolean).join(' · ')}</p>}
              </td>
              <td className="py-1.5 font-mono text-[11px] text-slate-400">{e.hash.slice(0, 10)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- tasks on this document (approve / reject / return)
export function TaskPanel({ objectRef }: { objectRef: string }) {
  const internal = useInternalUser();
  const { data } = useApi<Task[]>(internal ? '/tasks' : null);
  const mine = (data ?? []).filter((t) => t.object_ref === objectRef);
  if (!mine.length) return null;
  return (
    <div className="space-y-3">
      {mine.map((t) => <TaskDecision key={t.id} task={t} />)}
    </div>
  );
}

export function TaskDecision({ task, compact = false }: { task: Task; compact?: boolean }) {
  const [comment, setComment] = useState('');
  const decide = useCommand((decision: 'APPROVE' | 'REJECT' | 'RETURN') =>
    api.post(`/tasks/${task.id}/complete`, { decision, comment: comment || undefined }), { success: 'Decision recorded' });
  const overdue = task.due_at && new Date(task.due_at) < new Date();
  return (
    <div className={`rounded-lg border ${overdue ? 'border-amber-300 bg-amber-50/50' : 'border-blue-200 bg-blue-50/40'} p-4`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold">{task.name}</p>
          <p className="text-xs text-slate-600">Role {label(task.candidate_role)} · due {dateTime(task.due_at)}{task.escalation_level ? ` · escalated ×${task.escalation_level}` : ''}</p>
        </div>
        {overdue && <StatusChip status="OVERDUE" />}
      </div>
      {!compact && Object.keys(task.evidence ?? {}).length > 0 && (
        <p className="mt-2 font-mono text-[11px] text-slate-500">{JSON.stringify(task.evidence).slice(0, 240)}</p>
      )}
      <div className="mt-3 flex flex-col gap-2 md:flex-row md:items-end">
        <Textarea aria-label="Comment" placeholder="Comment (required to reject or return)" value={comment} onChange={(e) => setComment(e.target.value)} className="md:flex-1" />
        <div className="flex gap-2">
          <Button variant="primary" busy={decide.isPending} onClick={() => decide.mutate('APPROVE')}>Approve</Button>
          <Button busy={decide.isPending} onClick={() => decide.mutate('RETURN')} disabled={!comment}>Return</Button>
          <Button variant="danger" busy={decide.isPending} onClick={() => decide.mutate('REJECT')} disabled={!comment}>Reject</Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- object page pattern (§16)
export function ObjectPage({ type, docRef, eyebrow, title, status, facts, actions, lines, extraTabs = [], loading, error }: {
  type: string; docRef: string; eyebrow: string; title: ReactNode; status?: string; facts?: ReactNode; actions?: ReactNode;
  lines: ReactNode; extraTabs?: { id: string; label: string; content: ReactNode }[]; loading?: boolean; error?: Error | null;
}) {
  // Supplier-portal users cannot read the internal process, lineage and audit views.
  const internal = useInternalUser();
  if (loading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-xs uppercase tracking-wider text-slate-500">{eyebrow}</p>
          <div className="mt-1 flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-[#0B1020]">{title}</h1>
            {status && <StatusChip status={status} />}
          </div>
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      <TaskPanel objectRef={docRef} />
      {facts && <Card>{facts}</Card>}
      <Card>
        <Tabs tabs={[
          { id: 'lines', label: 'Lines', content: lines },
          ...extraTabs,
          ...(internal ? [
            { id: 'process', label: 'Process', content: <ProcessPath type={type} objectRef={docRef} /> },
            { id: 'lineage', label: 'Lineage', content: <LineageView type={type} objectRef={docRef} /> },
            { id: 'audit', label: 'Audit', content: <AuditTrail type={type} objectRef={docRef} /> },
          ] : []),
        ]} />
      </Card>
    </div>
  );
}

/** False for supplier-portal users. The cookie is read on the client only (server snapshot null), so markup matches. */
const noSubscribe = () => () => {};
function useInternalUser(): boolean {
  const cookie = useSyncExternalStore(noSubscribe, () => document.cookie, () => null);
  return useMemo(() => cookie === null || !readSessionUser()?.roles.includes('SUPPLIER_USER'), [cookie]);
}
