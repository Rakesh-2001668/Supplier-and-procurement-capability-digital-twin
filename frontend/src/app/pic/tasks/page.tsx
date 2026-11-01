'use client';

import Link from 'next/link';
import { useCallback, useMemo, useState } from 'react';
import { TaskDecision } from '@/components/pic/object';
import { Button, Card, Empty, Field, Input, Loading, PageHeader, ProblemBox, Select, Textarea } from '@/components/pic/ui';
import { BulkResult, BulkResults, SavedViews } from '@/components/pic/views';
import { api } from '@/lib/pic/api';
import { label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { docHref } from '@/lib/pic/links';

type Task = { id: string; name: string; kind: string; object_type: string; object_id: string; object_ref: string; candidate_role: string;
  due_at: string | null; escalation_level: number; evidence: Record<string, unknown> };
type Filters = { type: string; overdue: boolean; search: string };
const NO_FILTERS: Filters = { type: '', overdue: false, search: '' };

export default function TaskInbox() {
  const { data, isLoading, error } = useApi<Task[]>('/tasks');
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [comment, setComment] = useState('');
  const [result, setResult] = useState<BulkResult | null>(null);
  const apply = useCallback((f: Record<string, unknown>) => setFilters({ ...NO_FILTERS, ...(f as Partial<Filters>) }), []);

  const types = useMemo(() => [...new Set((data ?? []).map((t) => t.object_type))].sort(), [data]);
  const visible = (data ?? []).filter((t) => (!filters.type || t.object_type === filters.type)
    && (!filters.overdue || (t.due_at && new Date(t.due_at) < new Date()))
    && (!filters.search || `${t.object_ref} ${t.name}`.toLowerCase().includes(filters.search.toLowerCase())));
  const chosen = visible.filter((t) => selected.has(t.id));

  const bulk = useCommand((decision: 'APPROVE' | 'REJECT' | 'RETURN') => api.post<BulkResult>('/tasks/bulk-complete', {
    items: chosen.map((t) => ({ task_id: t.id, decision, comment: comment.trim() || undefined })),
  }), {
    onSuccess: (r) => {
      setResult(r);
      setSelected(new Set(r.results.filter((x) => !x.ok).map((x) => x.taskId)));  // refused rows stay selected
    },
  });

  function toggle(id: string) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  return (
    <div>
      <PageHeader eyebrow="REQ-03 · Approval inbox" title="Task inbox"
        subtitle="Approvals, steward decisions and reviews waiting for you. You never see tasks on documents you started or already approved (four-eyes)." />
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : !data?.length ? (
        <Empty title="You're all caught up" hint="New tasks appear here immediately when a document reaches your step." />
      ) : (
        <div className="space-y-4">
          <Card title="Filter and bulk decide" actions={<SavedViews screen="tasks" filters={filters} onApply={apply} />}>
            <div className="grid gap-3 md:grid-cols-4">
              <Field label="Document type">{(id) => <Select id={id} value={filters.type} onChange={(e) => setFilters({ ...filters, type: e.target.value })}
                options={[{ value: '', label: 'All types' }, ...types.map((t) => ({ value: t, label: label(t) }))]} />}</Field>
              <Field label="Search reference or step">{(id) => <Input id={id} value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} />}</Field>
              <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" className="accent-[#1A56DB]" checked={filters.overdue}
                onChange={(e) => setFilters({ ...filters, overdue: e.target.checked })} /> Overdue only</label>
              <div className="flex items-end gap-2">
                <Button onClick={() => setSelected(new Set(visible.map((t) => t.id)))}>Select all {visible.length}</Button>
                <Button variant="ghost" onClick={() => setSelected(new Set())} disabled={!selected.size}>Clear</Button>
              </div>
            </div>
            {selected.size > 0 && (
              <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50/50 p-3" role="region" aria-label="Bulk actions">
                <p className="text-sm font-medium">{chosen.length} task{chosen.length === 1 ? '' : 's'} selected{selected.size !== chosen.length ? ` (${selected.size - chosen.length} hidden by the filter are not included)` : ''}</p>
                <div className="mt-2 flex flex-col gap-2 md:flex-row md:items-end">
                  <Textarea aria-label="Comment for the selected tasks" placeholder="Comment (required to reject or return)" value={comment} onChange={(e) => setComment(e.target.value)} className="md:flex-1" />
                  <div className="flex gap-2">
                    <Button variant="primary" busy={bulk.isPending} disabled={!chosen.length} onClick={() => bulk.mutate('APPROVE')}>Approve selected</Button>
                    <Button busy={bulk.isPending} disabled={!chosen.length || !comment.trim()} onClick={() => bulk.mutate('RETURN')}>Return</Button>
                    <Button variant="danger" busy={bulk.isPending} disabled={!chosen.length || !comment.trim()} onClick={() => bulk.mutate('REJECT')}>Reject</Button>
                  </div>
                </div>
                <p className="mt-2 text-xs text-slate-600">Each task is checked on its own: your role, four-eyes and the comment rule apply per row, and you see the result of every row.</p>
              </div>
            )}
          </Card>
          {!visible.length && <Empty title="No task matches the filters" />}
          {visible.map((t) => {
            const href = docHref(t.object_type, t.object_ref, t.object_id);
            return (
              <Card key={t.id} title={
                <span className="flex items-center gap-2">
                  <input type="checkbox" className="accent-[#1A56DB]" checked={selected.has(t.id)} onChange={() => toggle(t.id)} aria-label={`Select ${t.object_ref}`} />
                  <span>{t.object_type.replace(/_/g, ' ').toLowerCase()} · {href ? <Link className="text-[#1A56DB] hover:underline" href={href}>{t.object_ref}</Link> : t.object_ref}</span>
                </span>}>
                <TaskDecision task={t} />
              </Card>
            );
          })}
        </div>
      )}
      {result && <BulkResults result={result} onClose={() => setResult(null)} />}
    </div>
  );
}
