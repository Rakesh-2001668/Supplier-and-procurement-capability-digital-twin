'use client';

// SRC-01 cockpit: events per stage with value, age and the next step (GET /v1/sourcing/pipeline).
import Link from 'next/link';
import { useState } from 'react';
import { Empty, Field, Input, Loading, ProblemBox, StatusChip } from '@/components/pic/ui';
import { dateTime, inr, label } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';

type PipelineEvent = { number: string; title: string; type: string; category: string; round: number; closeAt: string | null; ageDays: number; overdue: boolean;
  baselineMinor: number | null; competitive: boolean | null; next: string | null };
type Stage = { stage: string; label: string; count: number; valueMinor: number; events: PipelineEvent[] };
type Pipeline = { asOf: string; stages: Stage[]; total: number; open: number };

export function PipelineView() {
  const [category, setCategory] = useState('');
  const q = category.trim() ? `?category=${encodeURIComponent(category.trim().toUpperCase())}` : '';
  const { data, isLoading, error } = useApi<Pipeline>(`/sourcing/pipeline${q}`);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="max-w-2xl text-sm text-slate-600">Every event by stage with the value it is expected to award (baseline), how long it has been in the stage and what it needs next.</p>
        <div className="w-56"><Field label="Category">{(id) => <Input id={id} value={category} onChange={(e) => setCategory(e.target.value)} placeholder="all categories" />}</Field></div>
      </div>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : !data ? null : (
        <>
          <p className="text-sm text-slate-700" role="status">{data.total} event(s), {data.open} in progress · as of {dateTime(data.asOf)}</p>
          <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-4" aria-label="Pipeline stages">
            {data.stages.map((s) => (
              <li key={s.stage} className="flex flex-col rounded-xl border border-slate-200 bg-white">
                <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2">
                  <h3 className="text-sm font-semibold">{s.label}</h3>
                  <span className="text-xs text-slate-500"><span className="font-semibold tabular-nums text-slate-900">{s.count}</span> · {inr(s.valueMinor)}</span>
                </div>
                {!s.events.length ? <p className="px-4 py-3 text-xs text-slate-500">No events</p> : (
                  <ul className="max-h-96 divide-y divide-slate-100 overflow-y-auto">
                    {s.events.slice(0, 12).map((e) => (
                      <li key={e.number} className="px-4 py-2 text-sm">
                        <div className="flex flex-wrap items-center gap-2">
                          <Link href={`/pic/sourcing/${encodeURIComponent(e.number)}`} className="font-medium text-[#1A56DB] hover:underline">{e.number}</Link>
                          <span className="text-[11px] uppercase text-slate-500">{label(e.type)}</span>
                          {e.overdue && <StatusChip status="OVERDUE" />}
                          {e.competitive === false && <span className="rounded bg-amber-50 px-1 py-0.5 text-[10px] font-semibold uppercase text-amber-800">limited competition</span>}
                        </div>
                        <p className="truncate text-slate-700" title={e.title}>{e.title}</p>
                        <p className="text-xs text-slate-500">{e.category} · round {e.round} · {e.ageDays} d in stage · {e.baselineMinor ? inr(e.baselineMinor) : 'no baseline'}</p>
                        {e.next && <p className="text-xs text-slate-600">Next: {e.next}</p>}
                      </li>
                    ))}
                    {s.events.length > 12 && <li className="px-4 py-2 text-xs text-slate-500">and {s.events.length - 12} more: filter by category or use the worklist</li>}
                  </ul>
                )}
              </li>
            ))}
          </ol>
          {data.total === 0 && <Empty title="No sourcing events" />}
        </>
      )}
    </div>
  );
}
