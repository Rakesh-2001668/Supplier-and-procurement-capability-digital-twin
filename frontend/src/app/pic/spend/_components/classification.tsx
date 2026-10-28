'use client';

import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { SpendProblem } from './shared';

type Alternative = { category: string; score: number; evidence: string[] };
type Review = {
  id: string; invoice_ref: string; description: string; proposed_category: string; confidence: string; alternatives: Alternative[];
  status: string; decided_category: string | null; decided_at: string | null; agent_run_ref: string | null; created_at: string;
};
type Reviews = { categories: { code: string; name: string }[]; reviews: Review[] };

const STATUSES = [{ value: 'OPEN', label: 'Open' }, { value: 'ACCEPTED', label: 'Accepted' }, { value: 'RECLASSIFIED', label: 'Reclassified' }];

/** Steward queue for spend lines the Spend Classification Agent classified below the confidence threshold. */
export function ClassificationTab() {
  const [status, setStatus] = useState('OPEN');
  const [deciding, setDeciding] = useState<Review | null>(null);
  const { data, isLoading, error } = useApi<Reviews>(`/spend/classification-reviews?status=${status}`);
  const categories = data?.categories ?? [];
  const name = (code: string | null) => (code ? categories.find((c) => c.code === code)?.name ?? code : '–');

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">
        Lines classified with confidence below the tenant threshold wait here. Accepting or reclassifying sets the category with full confidence and feeds the decision back to the agent.
        Reviews are decided by a category manager, data steward or the procurement head.
      </p>
      <Card title="Classification review queue" actions={
        <Select aria-label="Filter reviews by status" value={status} onChange={(e) => setStatus(e.target.value)} options={STATUSES} />
      }>
        {isLoading ? <Loading /> : error ? <SpendProblem error={error} permission="spend:read or mdm:request" /> : (
          <DataTable<Review> rows={data?.reviews ?? []} empty={status === 'OPEN' ? 'No lines waiting for review' : 'No decided reviews'} columns={[
            { key: 'invoice_ref', header: 'Invoice', render: (r) => <span className="font-mono text-xs">{r.invoice_ref}</span> },
            { key: 'description', header: 'Description', className: 'min-w-[200px]' },
            { key: 'proposed_category', header: 'Proposed', render: (r) => <span><span className="font-mono text-xs font-semibold">{r.proposed_category}</span><br /><span className="text-xs text-slate-500">{name(r.proposed_category)}</span></span> },
            { key: 'confidence', header: 'Confidence', align: 'right', render: (r) => <span className={Number(r.confidence) < 0.5 ? 'font-semibold text-red-700' : 'text-amber-700'}>{(Number(r.confidence) * 100).toFixed(0)}%</span> },
            { key: 'alternatives', header: 'Evidence', render: (r) => (
              <ul className="space-y-0.5 text-xs text-slate-600">
                {(r.alternatives ?? []).map((a) => (
                  <li key={a.category}><span className="font-mono">{a.category}</span> · score {a.score}{a.evidence?.length ? ` · “${a.evidence.join('”, “')}”` : ' · supplier prior only'}</li>
                ))}
              </ul>
            ) },
            { key: 'status', header: 'Status', render: (r) => (
              <span><StatusChip status={r.status} />{r.decided_category && <span className="mt-0.5 block text-xs text-slate-500">{r.decided_category} · {dateTime(r.decided_at)}</span>}</span>
            ) },
            { key: 'actions', header: '', render: (r) => (r.status === 'OPEN' ? <Button variant="primary" onClick={() => setDeciding(r)}>Decide</Button> : null) },
          ]} />
        )}
      </Card>
      {deciding && <DecisionDialog review={deciding} categories={categories} onClose={() => setDeciding(null)} />}
    </div>
  );
}

function DecisionDialog({ review, categories, onClose }: { review: Review; categories: { code: string; name: string }[]; onClose: () => void }) {
  const [category, setCategory] = useState(review.proposed_category);
  const [comment, setComment] = useState('');
  const accepted = category === review.proposed_category;
  const decide = useCommand(() => api.post<Review>(`/spend/classification-reviews/${review.id}/decision`, { category, comment: comment.trim() || undefined }), {
    success: (r) => `${review.invoice_ref} ${r.status === 'ACCEPTED' ? 'accepted as' : 'reclassified to'} ${category}`, onSuccess: onClose });
  const options = categories.some((c) => c.code === review.proposed_category) ? categories : [{ code: review.proposed_category, name: review.proposed_category }, ...categories];
  return (
    <Dialog open title={`Classify – ${review.invoice_ref}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">“{review.description}” · agent proposed <span className="font-mono">{review.proposed_category}</span> at {(Number(review.confidence) * 100).toFixed(0)}% confidence.</p>
      <div className="grid gap-3">
        <Field label="Category">{(id) => (
          <Select id={id} value={category} onChange={(e) => setCategory(e.target.value)} options={options.map((c) => ({ value: c.code, label: `${c.code} · ${c.name}${c.code === review.proposed_category ? ' (proposed)' : ''}` }))} />
        )}</Field>
        <Field label="Comment (optional)">{(id) => <Textarea id={id} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="e.g. Consumables bought for the die-casting cell are MRO" />}</Field>
      </div>
      {decide.error && <div className="mt-3"><ProblemBox error={decide.error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={decide.isPending} onClick={() => decide.mutate()}>{accepted ? 'Accept proposal' : 'Reclassify'}</Button>
      </div>
    </Dialog>
  );
}
