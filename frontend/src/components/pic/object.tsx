'use client';

import Link from 'next/link';
import { ReactNode, useMemo, useState, useSyncExternalStore } from 'react';
import { api, readSessionUser } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { docHref, TYPE_LABEL } from '@/lib/pic/links';
import { Button, Card, CopyButton, Empty, Loading, ProblemBox, StatusChip, Tabs, Textarea } from './ui';
import { ProcessDiagram } from './bpmn-viewer';

type Step = { step: string; name: string; lane: string; type: string; status: string; actor: string | null; outcome: string | null; at: string };
type ProcessHistory = { id: string; process: string; version: number; flow: string; name: string; status: string; currentStep: string; path: Step[];
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
          <div className="mb-4">
            <ProcessDiagram processKey={p.process} version={p.version} height={340}
              done={p.path.filter((s) => s.status !== 'ACTIVE').map((s) => s.step)}
              active={p.status === 'RUNNING' ? (p.path.find((s) => s.status === 'ACTIVE')?.step ?? p.currentStep) : null} />
          </div>
          <ol className="relative ml-3 border-l-2 border-line">
            {p.path.map((s, i) => (
              <li key={`${s.step}-${i}`} className="mb-3 ml-5">
                <span className={`absolute -left-[9px] mt-1 flex h-4 w-4 items-center justify-center rounded-full ring-4 ring-white ${s.status === 'ACTIVE' ? 'bg-amber-400' : s.status === 'SKIPPED' ? 'bg-slate-300' : 'bg-emerald-500'}`} aria-hidden />
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-mono text-xs text-ink-3">{s.step}</span>
                  <span className="text-sm font-medium">{s.name}</span>
                  <span className="text-xs text-ink-3">· {s.lane}</span>
                  {s.status !== 'COMPLETED' && <StatusChip status={s.status === 'ACTIVE' ? 'ACTIVE_STEP' : s.status} />}
                </div>
                {s.outcome && <p className="text-sm text-ink-2">{s.outcome}</p>}
                <p className="text-xs text-ink-3">{s.actor} · {dateTime(s.at)}</p>
              </li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- lineage (P10)
type LineageNode = { type: string; id: string; ref: string };
type LineageEdge = { from: string; to: string; type: string; fromLine: number | null; toLine: number | null };
type LineageResponse = { nodes: LineageNode[]; edges: LineageEdge[] };

const LIFECYCLE_STAGES: { id: string; label: string; icon: string; types: string[] }[] = [
  { id: 'DEMAND', label: 'Requisition & Demand', icon: '📝', types: ['MRP_RUN', 'MATERIAL_REQUEST', 'PLANNED_ORDER', 'REQUISITION'] },
  { id: 'SOURCING', label: 'Sourcing & Contract', icon: '🤝', types: ['SOURCING_EVENT', 'BID', 'CONTRACT'] },
  { id: 'ORDER', label: 'Purchase Order', icon: '📦', types: ['PURCHASE_ORDER'] },
  { id: 'RECEIPT', label: 'Fulfillment & Receipt', icon: '🚚', types: ['ASN', 'GOODS_RECEIPT', 'SERVICE_ENTRY', 'RETURN_DELIVERY'] },
  { id: 'SETTLEMENT', label: 'Invoice & Settlement', icon: '💳', types: ['INVOICE', 'CREDIT_NOTE', 'PAYMENT', 'ERP_DOCUMENT'] },
  { id: 'VALUE', label: 'Savings & Governance', icon: '📈', types: ['SAVINGS_INITIATIVE'] },
];

export function LineageView({ type, objectRef }: { type: string; objectRef: string }) {
  const { data, isLoading, error } = useApi<LineageResponse>(`/lineage/${type}/${encodeURIComponent(objectRef)}`);
  const [viewMode, setViewMode] = useState<'graph' | 'list'>('graph');
  const [selectedRef, setSelectedRef] = useState<string>(objectRef);
  const [search, setSearch] = useState<string>('');

  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data?.nodes.length && !data?.edges.length) return <Empty title="No linked documents yet" />;

  const nodes = Object.fromEntries(data.nodes.map((n) => [n.ref, n]));
  const edges = data.edges;

  // Active focused node
  const activeNode = nodes[selectedRef] ?? nodes[objectRef] ?? data.nodes[0];

  // Upstream (edges where to === activeNode.ref)
  const incomingEdges = edges.filter((e) => e.to === activeNode?.ref);
  // Downstream (edges where from === activeNode.ref)
  const outgoingEdges = edges.filter((e) => e.from === activeNode?.ref);

  // Group nodes into stages
  const stageGroups: { stage: (typeof LIFECYCLE_STAGES)[number]; nodes: LineageNode[] }[] = [];
  const assignedRefs = new Set<string>();

  for (const st of LIFECYCLE_STAGES) {
    const stageNodes = data.nodes.filter((n) => st.types.includes(n.type));
    if (stageNodes.length > 0) {
      stageNodes.forEach((n) => assignedRefs.add(n.ref));
      stageGroups.push({ stage: st, nodes: stageNodes });
    }
  }

  // Any remaining nodes not matching the predefined stages
  const otherNodes = data.nodes.filter((n) => !assignedRefs.has(n.ref));
  if (otherNodes.length > 0) {
    stageGroups.push({
      stage: { id: 'OTHER', label: 'Other Documents', icon: '📑', types: [] },
      nodes: otherNodes,
    });
  }

  // Filtered edges for audit search
  const filteredEdges = edges.filter((e) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return e.from.toLowerCase().includes(q) || e.to.toLowerCase().includes(q) || e.type.toLowerCase().includes(q);
  });

  return (
    <div className="space-y-4">
      {/* View Switcher & Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-ink-3">Document Flow:</span>
          <div className="inline-flex rounded-lg border border-line bg-surface-3 p-0.5 text-xs font-medium">
            <button
              type="button"
              onClick={() => setViewMode('graph')}
              className={`rounded-md px-2.5 py-1 transition ${
                viewMode === 'graph' ? 'bg-surface text-ink shadow-sm' : 'text-ink-2 hover:text-ink'
              }`}
            >
              Visual Flow Diagram
            </button>
            <button
              type="button"
              onClick={() => setViewMode('list')}
              className={`rounded-md px-2.5 py-1 transition ${
                viewMode === 'list' ? 'bg-surface text-ink shadow-sm' : 'text-ink-2 hover:text-ink'
              }`}
            >
              Audit Trace List ({edges.length})
            </button>
          </div>
        </div>

        <div className="flex items-center gap-3 text-xs text-ink-3">
          <span>{data.nodes.length} documents linked</span>
          <span>·</span>
          <span>{edges.length} relationships</span>
        </div>
      </div>

      {viewMode === 'graph' ? (
        <div className="space-y-4">
          {/* Active Node Detail Strip */}
          {activeNode && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-blue-200 bg-gradient-to-r from-blue-50/80 via-white to-blue-50/30 p-3.5 shadow-sm">
              <div className="flex items-center gap-2.5">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand text-xs font-bold text-white shadow-sm">
                  {activeNode.ref === objectRef ? '★' : '•'}
                </span>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-bold text-ink">{activeNode.ref}</span>
                    <CopyButton text={activeNode.ref} />
                    <span className="rounded bg-blue-100 px-2 py-0.5 text-[11px] font-semibold text-blue-800">
                      {TYPE_LABEL[activeNode.type] ?? label(activeNode.type)}
                    </span>
                    {activeNode.ref === objectRef && (
                      <span className="flex items-center gap-1 rounded-full bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white">
                        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-surface" />
                        CURRENT DOCUMENT
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-3 text-xs text-ink-2">
                    <span>{incomingEdges.length} upstream predecessor(s)</span>
                    <span>·</span>
                    <span>{outgoingEdges.length} downstream dependent(s)</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                {activeNode.ref !== objectRef && (
                  <button
                    type="button"
                    onClick={() => setSelectedRef(objectRef)}
                    className="text-xs font-semibold text-brand-ink hover:underline"
                  >
                    Reset to current ({objectRef})
                  </button>
                )}
                {docHref(activeNode.type, activeNode.ref, activeNode.id) && (
                  <Link
                    href={docHref(activeNode.type, activeNode.ref, activeNode.id)!}
                    className="rounded-lg bg-brand px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-strong shadow-sm transition"
                  >
                    Open Document →
                  </Link>
                )}
              </div>
            </div>
          )}

          {/* Sequential Stage Columns (Swimlanes DAG) */}
          <div className="overflow-x-auto pb-2">
            <div className="flex min-w-[760px] items-start gap-3">
              {stageGroups.map((group, gIdx) => {
                const isFirst = gIdx === 0;
                return (
                  <div key={group.stage.id} className="flex flex-1 items-start gap-2">
                    {!isFirst && (
                      <div className="mt-8 flex flex-col items-center justify-center text-slate-300" aria-hidden>
                        <span className="text-lg font-bold">→</span>
                      </div>
                    )}
                    <div className="flex-1 rounded-2xl border border-line-strong/80 ring-1 ring-inset ring-black/[0.04] dark:ring-white/[0.06] bg-surface-2/60 p-3.5 shadow-card">
                      <div className="mb-3 flex items-center justify-between border-b border-line/70 pb-2">
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm">{group.stage.icon}</span>
                          <h4 className="text-xs font-bold uppercase tracking-wider text-ink-2">
                            {group.stage.label}
                          </h4>
                        </div>
                        <span className="rounded-full bg-surface-3 border border-line px-2 py-0.5 text-[10px] font-bold text-ink-2">
                          {group.nodes.length}
                        </span>
                      </div>

                      <div className="space-y-2.5">
                        {group.nodes.map((n) => {
                          const isCurrent = n.ref === objectRef;
                          const isSelected = n.ref === activeNode?.ref;
                          const href = docHref(n.type, n.ref, n.id);
                          const nodeIncoming = edges.filter((e) => e.to === n.ref);
                          const nodeOutgoing = edges.filter((e) => e.from === n.ref);

                          return (
                            <div
                              key={n.ref}
                              onClick={() => setSelectedRef(n.ref)}
                              role="button"
                              tabIndex={0}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault();
                                  setSelectedRef(n.ref);
                                }
                              }}
                              className={`group relative cursor-pointer rounded-xl border p-3 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                                isSelected
                                  ? 'border-brand bg-surface ring-2 ring-brand shadow-raised -translate-y-0.5'
                                  : isCurrent
                                  ? 'border-blue-400 bg-blue-50/50 hover:border-brand hover:shadow-card'
                                  : 'border-line-strong/70 ring-1 ring-inset ring-black/[0.03] dark:ring-white/[0.05] bg-surface hover:border-brand/50 hover:shadow-card hover:-translate-y-0.5'
                              }`}
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span className="rounded bg-surface-3 px-1.5 py-0.5 text-[10px] font-semibold text-ink-2">
                                  {TYPE_LABEL[n.type] ?? label(n.type)}
                                </span>
                                {isCurrent && (
                                  <span className="flex h-2 w-2 rounded-full bg-blue-600 ring-4 ring-blue-100" title="Current Document" />
                                )}
                              </div>

                              <p className="mt-1 font-mono text-xs font-bold text-ink group-hover:text-brand-ink">
                                {n.ref}
                              </p>

                              {/* Connected Badges */}
                              <div className="mt-2 flex flex-wrap items-center gap-1">
                                {nodeIncoming.map((edge, eIdx) => (
                                  <span
                                    key={eIdx}
                                    className="rounded bg-surface-3 px-1 py-0.5 font-mono text-[9px] text-ink-2"
                                    title={`From ${edge.from}`}
                                  >
                                    ← {edge.type.replace(/_/g, ' ').toLowerCase()}
                                  </span>
                                ))}
                                {nodeOutgoing.map((edge, eIdx) => (
                                  <span
                                    key={eIdx}
                                    className="rounded bg-blue-50 px-1 py-0.5 font-mono text-[9px] text-blue-700 font-semibold"
                                    title={`To ${edge.to}`}
                                  >
                                    {edge.type.replace(/_/g, ' ').toLowerCase()} →
                                  </span>
                                ))}
                              </div>

                              {href && (
                                <div className="mt-2 flex justify-end border-t border-line pt-1.5 text-[10px]">
                                  <Link
                                    href={href}
                                    prefetch={false}
                                    onClick={(e) => e.stopPropagation()}
                                    className="font-medium text-brand-ink hover:underline"
                                  >
                                    View details ↗
                                  </Link>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Trace Relationship Cards */}
          <div className="rounded-2xl border border-line-strong/80 ring-1 ring-inset ring-black/[0.04] dark:ring-white/[0.06] bg-surface p-5 shadow-card">
            <h4 className="text-xs font-bold uppercase tracking-wider text-ink mb-3.5">
              Direct Relationships for {activeNode?.ref}
            </h4>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {/* Predecessors */}
              <div className="rounded-xl border border-line-strong/70 ring-1 ring-inset ring-black/[0.03] dark:ring-white/[0.05] bg-surface-2/50 p-4 transition hover:border-line-strong hover:bg-surface-2/70">
                <span className="text-[11px] font-bold text-ink-3 uppercase tracking-wider">
                  Upstream Predecessors ({incomingEdges.length})
                </span>
                {!incomingEdges.length ? (
                  <p className="mt-2 text-xs text-ink-3 italic">No upstream documents (origin in lineage)</p>
                ) : (
                  <ul className="mt-2 space-y-1.5">
                    {incomingEdges.map((e, idx) => {
                      const fromNode = nodes[e.from];
                      return (
                        <li key={idx} className="flex items-center justify-between text-xs">
                          <div className="flex items-center gap-1.5">
                            <span className="font-mono text-ink-3">←</span>
                            <DocLink node={fromNode} line={e.fromLine} />
                          </div>
                          <span className="rounded bg-surface-3 border border-line px-1.5 py-0.5 font-mono text-[10px] text-ink-2 font-semibold">
                            {e.type.replace(/_/g, ' ').toLowerCase()}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>

              {/* Successors */}
              <div className="rounded-xl border border-line-strong/70 ring-1 ring-inset ring-black/[0.03] dark:ring-white/[0.05] bg-surface-2/50 p-4 transition hover:border-line-strong hover:bg-surface-2/70">
                <span className="text-[11px] font-bold text-ink-3 uppercase tracking-wider">
                  Downstream Successors ({outgoingEdges.length})
                </span>
                {!outgoingEdges.length ? (
                  <p className="mt-2 text-xs text-ink-3 italic">No downstream documents yet</p>
                ) : (
                  <ul className="mt-2 space-y-1.5">
                    {outgoingEdges.map((e, idx) => {
                      const toNode = nodes[e.to];
                      return (
                        <li key={idx} className="flex items-center justify-between text-xs">
                          <span className="rounded bg-blue-500/10 border border-blue-500/20 px-1.5 py-0.5 font-mono text-[10px] text-brand-ink font-bold">
                            {e.type.replace(/_/g, ' ').toLowerCase()}
                          </span>
                          <div className="flex items-center gap-1.5">
                            <span className="font-mono text-ink-3">→</span>
                            <DocLink node={toNode} line={e.toLine} />
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* Audit Trace List View */
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <input
              type="text"
              placeholder="Filter trace by reference or relation…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="max-w-sm rounded-lg border border-line-strong px-3 py-1.5 text-xs focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
            />
            <span className="text-xs text-ink-3">
              Showing {filteredEdges.length} of {edges.length} link(s)
            </span>
          </div>

          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="min-w-full divide-y divide-line text-xs">
              <thead className="bg-surface-2 text-left uppercase tracking-wider text-ink-3">
                <tr>
                  <th className="px-3 py-2.5">Origin Document</th>
                  <th className="px-3 py-2.5 text-center">Relationship</th>
                  <th className="px-3 py-2.5">Target Document</th>
                  <th className="px-3 py-2.5 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line bg-surface">
                {filteredEdges.map((e, idx) => {
                  const fromNode = nodes[e.from];
                  const toNode = nodes[e.to];
                  const involvesCurrent = e.from === objectRef || e.to === objectRef;

                  return (
                    <tr
                      key={idx}
                      className={`hover:bg-surface-2/60 ${involvesCurrent ? 'bg-blue-50/30' : ''}`}
                    >
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <DocLink node={fromNode} line={e.fromLine} />
                          {e.from === objectRef && (
                            <span className="rounded bg-blue-100 px-1 py-0.5 text-[9px] font-bold text-blue-800">
                              CURRENT
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <span className="inline-block rounded bg-surface-3 px-2 py-0.5 font-mono text-[10px] text-ink-2">
                          {e.type.replace(/_/g, ' ').toLowerCase()} →
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <DocLink node={toNode} line={e.toLine} />
                          {e.to === objectRef && (
                            <span className="rounded bg-blue-100 px-1 py-0.5 text-[9px] font-bold text-blue-800">
                              CURRENT
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedRef(e.from === objectRef ? e.to : e.from);
                            setViewMode('graph');
                          }}
                          className="font-medium text-brand-ink hover:underline"
                        >
                          View in diagram
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function DocLink({ node, line }: { node?: { type: string; id: string; ref: string }; line: number | null }) {
  if (!node) return null;
  const href = docHref(node.type, node.ref, node.id);
  const text = `${TYPE_LABEL[node.type] ?? label(node.type)} ${node.ref}${line ? ` / ${line}` : ''}`;
  return href ? <Link href={href} className="font-medium text-brand-ink hover:underline">{text}</Link> : <span className="font-medium">{text}</span>;
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
        <thead><tr className="text-left text-xs uppercase tracking-wide text-ink-3">
          <th className="py-1 pr-4">When</th><th className="py-1 pr-4">Action</th><th className="py-1 pr-4">Actor</th><th className="py-1 pr-4">Detail</th><th className="py-1">Hash</th>
        </tr></thead>
        <tbody className="divide-y divide-line">
          {data.map((e) => (
            <tr key={e.seq} className="align-top">
              <td className="whitespace-nowrap py-1.5 pr-4 text-ink-2">{dateTime(e.ts)}</td>
              <td className="py-1.5 pr-4 font-medium">{label(e.action)}</td>
              <td className="py-1.5 pr-4 text-ink-2">{e.actor}</td>
              <td className="py-1.5 pr-4 text-ink-2">
                {e.reason && <p>{e.reason}</p>}
                {e.after ? <p className="font-mono text-[11px] text-ink-3">{JSON.stringify(e.after).slice(0, 180)}</p> : null}
                {(e.ruleSetVersion || e.aiRef) && <p className="font-mono text-[11px] text-ink-3">{[e.ruleSetVersion, e.aiRef].filter(Boolean).join(' · ')}</p>}
              </td>
              <td className="py-1.5 font-mono text-[11px] text-ink-3">
                <CopyButton text={e.hash} label={e.hash.slice(0, 8)} />
              </td>
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
          <p className="text-xs text-ink-2">Role {label(task.candidate_role)} · due {dateTime(task.due_at)}{task.escalation_level ? ` · escalated ×${task.escalation_level}` : ''}</p>
        </div>
        {overdue && <StatusChip status="OVERDUE" />}
      </div>
      {!compact && Object.keys(task.evidence ?? {}).length > 0 && (
        <p className="mt-2 font-mono text-[11px] text-ink-3">{JSON.stringify(task.evidence).slice(0, 240)}</p>
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

// ---------------------------------------------------------------- approvals tab (tasks and decisions of the document)
type ApprovalTask = { id: string; name: string; kind: string; role: string; sequence: number; status: string; decision: string | null; comment: string | null;
  decidedBy: string | null; decidedAt: string | null; dueAt: string | null; escalationLevel: number; createdAt: string };

export function ApprovalsTab({ type, objectRef }: { type: string; objectRef: string }) {
  const { data, isLoading, error } = useApi<{ chain: string[]; tasks: ApprovalTask[] }>(`/documents/${type}/${encodeURIComponent(objectRef)}/approvals`);
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data?.tasks.length) return <Empty title="No approvals on this document" hint="Approval tasks appear here when a rule routes the document to an approver." />;
  return (
    <div className="space-y-3">
      {data.chain.length > 0 && <p className="text-sm text-ink-2">Approval chain: {data.chain.map(label).join(' → ')}</p>}
      <ol className="space-y-2" aria-label="Approval tasks">
        {data.tasks.map((t) => (
          <li key={t.id} className="rounded-lg border border-line p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold">{t.name}</p>
              <StatusChip status={t.decision ?? t.status} />
            </div>
            <p className="text-xs text-ink-2">
              Role {label(t.role)}{t.decidedBy ? ` · ${t.decidedBy}` : ''}{t.decidedAt ? ` · ${dateTime(t.decidedAt)}` : t.dueAt ? ` · due ${dateTime(t.dueAt)}` : ''}
              {t.escalationLevel ? ` · escalated ×${t.escalationLevel}` : ''}
            </p>
            {t.comment && <p className="mt-1 text-sm text-ink-2">“{t.comment}”</p>}
          </li>
        ))}
      </ol>
    </div>
  );
}

// ---------------------------------------------------------------- documents tab (printouts, EDI / ERP documents, signatures, linked documents)
type DocItem = { kind: string; title: string; status: string | null; at: string; hash?: string; href?: string; recipient?: string; source?: string; direction?: string;
  linkedType?: string; linkedRef?: string; linkedId?: string };

export function DocumentsTab({ type, objectRef }: { type: string; objectRef: string }) {
  const { data, isLoading, error } = useApi<{ items: DocItem[]; counts: Record<string, number> }>(`/documents/${type}/${encodeURIComponent(objectRef)}/files`);
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data?.items.length) return <Empty title="No documents yet" hint="Printouts, EDI and ERP documents, signatures and linked documents are listed here." />;
  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-2">{Object.entries(data.counts).map(([k, n]) => `${n} ${label(k).toLowerCase()}`).join(' · ')}</p>
      <ul className="divide-y divide-line" aria-label="Documents">
        {data.items.map((d, i) => {
          const link = d.linkedType && d.linkedRef ? docHref(d.linkedType, d.linkedRef, d.linkedId) : null;
          return (
            <li key={`${d.kind}-${i}`} className="flex flex-wrap items-start justify-between gap-2 py-2 text-sm">
              <div>
                <p className="font-medium">
                  <span className="mr-2 rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[10px] uppercase text-ink-2">{label(d.kind)}</span>
                  {link ? <Link href={link} className="text-brand-ink hover:underline">{d.title}</Link> : d.title}
                </p>
                <p className="text-xs text-ink-3">{dateTime(d.at)}{d.recipient ? ` · to ${d.recipient}` : ''}{d.source ? ` · ${d.source}` : ''}{d.hash ? ` · sha256 ${d.hash.slice(0, 12)}…` : ''}</p>
              </div>
              <div className="flex items-center gap-3">
                {d.status && <StatusChip status={d.status} />}
                {d.href && <a href={`/api/pic/v1${d.href}`} target="_blank" rel="noreferrer" className="text-brand-ink hover:underline">Open<span className="sr-only"> {d.title} in a new tab</span></a>}
              </div>
            </li>
          );
        })}
      </ul>
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
          <p className="font-mono text-xs uppercase tracking-wider text-ink-3">{eyebrow}</p>
          <div className="mt-1 flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
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
          ...(internal ? [
            { id: 'approvals', label: 'Approvals', content: <ApprovalsTab type={type} objectRef={docRef} /> },
            { id: 'documents', label: 'Documents', content: <DocumentsTab type={type} objectRef={docRef} /> },
          ] : []),
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
