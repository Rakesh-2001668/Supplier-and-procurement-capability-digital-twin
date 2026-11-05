'use client';

import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, Kpi, Loading, ProblemBox, Select, StatusChip, Tabs, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { crore, dateTime, inr, label, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { SpendProblem } from './shared';
import { TaxonomyPanel, TaxonomyNode } from './taxonomy';

type Alternative = { category: string; score: number; evidence: string[] };
type Item = {
  id: string; invoice_ref: string; description: string; proposed_category: string; status: string; decided_category: string | null; channel: string | null;
  first_category: string | null; confidence: string; alternatives: Alternative[]; valueMinor: number; dueAt: string | null; overdue: boolean; ageDays: number; fourEyes: boolean;
  supplier: string; supplierName: string; plant: string | null; period: string | null; currency: string | null; amountMinor: number | null; firstDecidedBy: string | null;
  learnedKeyword: string | null;
};
type Summary = {
  byStatus: Record<string, { count: number; valueMinor: number }>; open: number; overdue: number; overdueValueMinor: number; oldestDays: number; averageAgeDays: number;
  ageBuckets: Record<string, number>; acceptRatePct: string | null;
};
type Queue = { total: number; items: Item[]; summary: Summary; fourEyesAboveMinor: number };
type BulkResult = { selected: number; results: { id: string; invoice: string; status: string; code?: string; message?: string }[] };

const STATUSES = [
  { value: 'OPEN', label: 'Open' }, { value: 'PENDING_SECOND', label: 'Waiting for a second steward' }, { value: 'ACCEPTED', label: 'Accepted' }, { value: 'RECLASSIFIED', label: 'Reclassified' },
];
const SORTS = [{ value: 'value', label: 'Largest value first' }, { value: 'due', label: 'Due date (SLA)' }, { value: 'age', label: 'Oldest first' }, { value: 'confidence', label: 'Lowest confidence' }];
const PAGE = 100;

/** Steward queue for lines the Spend Classification Agent was not sure of, and the taxonomy those decisions maintain. */
export function ClassificationTab() {
  return (
    <Tabs label="Classification views" tabs={[
      { id: 'queue', label: 'Steward queue', content: <QueueView /> },
      { id: 'taxonomy', label: 'Taxonomy', content: <TaxonomyPanel /> },
    ]} />
  );
}

function QueueView() {
  const [status, setStatus] = useState('OPEN');
  const [sort, setSort] = useState('value');
  const [overdue, setOverdue] = useState('');
  const [minValue, setMinValue] = useState('');
  const [supplier, setSupplier] = useState('');
  const [text, setText] = useState('');
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deciding, setDeciding] = useState<Item | null>(null);
  const [bulk, setBulk] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkResult | null>(null);
  const qs = new URLSearchParams({ status, sort, limit: String(PAGE), offset: String(offset) });
  if (overdue) qs.set('overdue', overdue);
  if (minValue.trim() && Number(minValue) >= 0) qs.set('min_value', String(rupeesToMinor(minValue)));
  if (supplier.trim()) qs.set('supplier', supplier.trim());
  if (text.trim()) qs.set('text', text.trim());
  const queue = useApi<Queue>(`/spend/classification-queue?${qs.toString()}`);
  const taxonomy = useApi<TaxonomyNode[]>('/spend/taxonomy');
  const me = useApi<{ userId: string }>('/me');
  const data = queue.data;
  const items = data?.items ?? [];
  const categories = (taxonomy.data ?? []).filter((n) => n.active && n.level >= 3);
  const reset = () => { setOffset(0); setSelected(new Set()); };
  const sum = data?.summary;
  const workable = status === 'OPEN' || status === 'PENDING_SECOND';

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">
        Lines classified with confidence below the tenant threshold wait here, largest value first. Each has an SLA. Reclassifying a line worth {data ? inr(data.fourEyesAboveMinor) : 'the four-eyes value'} or more
        needs two different stewards to choose the same category; accepting the agent’s own proposal is one decision at any value.
      </p>
      {sum && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
          <Kpi label="Open" value={sum.open} hint={`${sum.byStatus.OPEN?.count ?? 0} open · ${sum.byStatus.PENDING_SECOND?.count ?? 0} waiting for a second steward`} tone={sum.open ? 'warn' : 'default'} />
          <Kpi label="Past SLA" value={sum.overdue} hint={crore(sum.overdueValueMinor)} tone={sum.overdue ? 'bad' : 'good'} />
          <Kpi label="Oldest" value={`${Math.max(0, sum.oldestDays)} d`} hint={`average ${Math.max(0, sum.averageAgeDays)} d`} />
          <Kpi label="Accept rate" value={sum.acceptRatePct === null ? '–' : `${sum.acceptRatePct}%`} hint="proposals accepted as made" />
          <Kpi label="Age buckets (days)" value={<span className="text-base">{Object.entries(sum.ageBuckets).map(([k, v]) => `${k}: ${v}`).join(' · ')}</span>} />
        </div>
      )}

      <Card title="Filters">
        <div className="grid gap-3 md:grid-cols-6">
          <Field label="Status">{(id) => <Select id={id} value={status} onChange={(e) => { setStatus(e.target.value); reset(); }} options={STATUSES} />}</Field>
          <Field label="Sort">{(id) => <Select id={id} value={sort} onChange={(e) => { setSort(e.target.value); reset(); }} options={SORTS} />}</Field>
          <Field label="SLA">{(id) => <Select id={id} value={overdue} onChange={(e) => { setOverdue(e.target.value); reset(); }}
            options={[{ value: '', label: 'All' }, { value: 'true', label: 'Past SLA only' }, { value: 'false', label: 'Within SLA only' }]} />}</Field>
          <Field label="Value from (₹)">{(id) => <Input id={id} inputMode="decimal" value={minValue} onChange={(e) => { setMinValue(e.target.value); reset(); }} />}</Field>
          <Field label="Supplier code">{(id) => <Input id={id} value={supplier} onChange={(e) => { setSupplier(e.target.value); reset(); }} />}</Field>
          <Field label="Description contains">{(id) => <Input id={id} value={text} onChange={(e) => { setText(e.target.value); reset(); }} />}</Field>
        </div>
      </Card>

      {bulkResult && (
        <Card title={`Bulk reclassification: ${bulkResult.selected} review${bulkResult.selected === 1 ? '' : 's'} selected`} actions={<Button variant="ghost" onClick={() => setBulkResult(null)}>Dismiss</Button>}>
          <DataTable<BulkResult['results'][number]> caption="Bulk reclassification results" rows={bulkResult.results} columns={[
            { key: 'invoice', header: 'Invoice', render: (r) => <span className="font-mono text-xs">{r.invoice}</span> },
            { key: 'status', header: 'Result', render: (r) => <StatusChip status={r.status} /> },
            { key: 'message', header: 'Why', render: (r) => (r.status === 'PENDING_SECOND' ? 'At or above the four-eyes value: parked for a second steward' : r.message ? `${r.message}${r.code ? ` (${r.code})` : ''}` : '–') },
          ]} />
        </Card>
      )}

      <Card title={`Classification review queue (${data?.total ?? 0})`} actions={workable && (
        <Button variant="primary" disabled={!items.length} onClick={() => setBulk(true)}>
          {selected.size ? `Reclassify ${selected.size} selected…` : 'Bulk reclassify…'}
        </Button>
      )}>
        {queue.isLoading ? <Loading /> : queue.error ? <SpendProblem error={queue.error} permission="spend:read or mdm:request" /> : (
          <>
            <DataTable<Item> caption="Classification review queue" rows={items} empty={workable ? 'No lines waiting for review' : 'No decided reviews'}
              selection={workable ? { selected, onChange: setSelected, rowId: ((r: Item) => r.id) as (row: never) => string, label: ((r: Item) => r.invoice_ref) as (row: never) => string } : undefined}
              columns={[
                { key: 'invoice_ref', header: 'Invoice', render: (r) => <span><span className="font-mono text-xs font-semibold">{r.invoice_ref}</span><span className="block text-xs text-slate-500">{r.period ?? ''} · {r.plant ?? '–'}</span></span> },
                { key: 'supplier', header: 'Supplier', render: (r) => <span><span className="font-mono text-xs">{r.supplier}</span><span className="block max-w-[160px] truncate text-xs text-slate-500" title={r.supplierName}>{r.supplierName}</span></span> },
                { key: 'description', header: 'Description', className: 'min-w-[180px]' },
                { key: 'valueMinor', header: 'Value', align: 'right', render: (r) => <span>{inr(r.valueMinor)}{r.fourEyes && <span className="block text-[11px] font-semibold text-blue-800">four eyes</span>}</span> },
                { key: 'proposed_category', header: 'Proposed', render: (r) => (
                  <span><span className="font-mono text-xs font-semibold">{r.proposed_category}</span><span className="block text-xs text-slate-500">{Number(r.confidence) >= 0 ? `${(Number(r.confidence) * 100).toFixed(0)}% confidence` : ''}</span></span>
                ) },
                { key: 'alternatives', header: 'Evidence', render: (r) => (
                  <ul className="space-y-0.5 text-xs text-slate-600">
                    {(r.alternatives ?? []).slice(0, 3).map((a) => <li key={a.category}><span className="font-mono">{a.category}</span> · {a.score}{a.evidence?.length ? ` · “${a.evidence.join('”, “')}”` : ' · supplier prior'}</li>)}
                  </ul>
                ) },
                { key: 'age', header: 'Age / SLA', render: (r) => (
                  <span className={r.overdue ? 'font-semibold text-red-700' : 'text-slate-700'}>{r.ageDays < 0 ? 'dated ahead' : `${r.ageDays} d`}{r.overdue && <span className="ml-1 text-[11px] uppercase">past SLA</span>}
                    <span className="block text-xs font-normal text-slate-500">due {r.dueAt ? dateTime(r.dueAt) : '–'}</span></span>
                ) },
                { key: 'status', header: 'Status', render: (r) => (
                  <span><StatusChip status={r.status === 'PENDING_SECOND' ? 'PENDING' : r.status} />
                    {r.status === 'PENDING_SECOND' && <span className="mt-0.5 block text-xs text-slate-600">first steward chose <span className="font-mono">{r.first_category}</span></span>}
                    {r.decided_category && <span className="mt-0.5 block text-xs text-slate-500">{r.decided_category}{r.channel ? ` · ${label(r.channel)}` : ''}{r.learnedKeyword ? ` · learned “${r.learnedKeyword}”` : ''}</span>}</span>
                ) },
                { key: 'actions', header: '', render: (r) => (workable ? <Button variant="primary" onClick={() => setDeciding(r)} aria-label={`${r.status === 'PENDING_SECOND' ? 'Confirm' : 'Decide'} ${r.invoice_ref}`}>{r.status === 'PENDING_SECOND' ? 'Confirm' : 'Decide'}</Button> : null) },
              ]} />
            {data && data.total > PAGE && (
              <div className="mt-3 flex items-center justify-between text-sm text-slate-600">
                <Button disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - PAGE)); setSelected(new Set()); }}>Previous</Button>
                <span>{offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}</span>
                <Button disabled={offset + PAGE >= data.total} onClick={() => { setOffset(offset + PAGE); setSelected(new Set()); }}>Next</Button>
              </div>
            )}
          </>
        )}
      </Card>
      {deciding && <DecisionDialog item={deciding} categories={categories} threshold={data?.fourEyesAboveMinor ?? 0} meId={me.data?.userId} onClose={() => setDeciding(null)} />}
      {bulk && <BulkDialog ids={[...selected]} text={text.trim()} supplier={supplier.trim()} categories={categories} onClose={() => setBulk(false)} onDone={(r) => { setBulkResult(r); setSelected(new Set()); setBulk(false); }} />}
    </div>
  );
}

function categoryOptions(categories: TaxonomyNode[], proposed: string) {
  const list = categories.some((c) => c.code === proposed) ? categories : [{ code: proposed, name: proposed } as TaxonomyNode, ...categories];
  return list.map((c) => ({ value: c.code, label: `${c.code} · ${c.name}${c.code === proposed ? ' (proposed)' : ''}` }));
}

function DecisionDialog({ item, categories, threshold, meId, onClose }: { item: Item; categories: TaxonomyNode[]; threshold: number; meId?: string; onClose: () => void }) {
  const second = item.status === 'PENDING_SECOND';
  const [category, setCategory] = useState(second && item.first_category ? item.first_category : item.proposed_category);
  const [comment, setComment] = useState('');
  const [reason, setReason] = useState('');
  const [keyword, setKeyword] = useState('');
  const accepted = category === item.proposed_category;
  const parks = !second && !accepted && item.valueMinor >= threshold;
  const sameUser = second && !!meId && item.firstDecidedBy === meId;
  const kwOk = !keyword.trim() || (keyword.trim().length >= 4 && keyword.trim().length <= 40);
  const decide = useCommand(() => api.post<{ status: string }>(`/spend/classification-reviews/${item.id}/decision`, {
    category, comment: comment.trim() || undefined, reason: reason.trim() || undefined, learn_keyword: keyword.trim() || undefined,
  }), {
    success: (r) => (r.status === 'PENDING_SECOND' ? `${item.invoice_ref} parked: a second steward must choose ${category}` : `${item.invoice_ref} ${r.status === 'ACCEPTED' ? 'accepted as' : 'reclassified to'} ${category}`),
    onSuccess: onClose,
  });
  return (
    <Dialog open title={`${second ? 'Confirm' : 'Classify'} – ${item.invoice_ref}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">
        “{item.description}” · {item.supplier} · {inr(item.valueMinor)} · agent proposed <span className="font-mono">{item.proposed_category}</span> at {(Number(item.confidence) * 100).toFixed(0)}%.
      </p>
      {second && (
        <p className="mb-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900" role="note">
          A first steward chose <span className="font-mono font-semibold">{item.first_category}</span>. Choose the same category to confirm it; a different category reopens the review.
          {sameUser && ' You made the first decision, so the platform will refuse your confirmation: it needs a different steward.'}
        </p>
      )}
      {parks && (
        <p className="mb-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900" role="note">
          This line is worth {inr(item.valueMinor)}, at or above {inr(threshold)}. Your decision is recorded as the first of two: a different steward must choose the same category.
        </p>
      )}
      <div className="grid gap-3">
        <Field label="Category" hint={categories.length ? undefined : 'Loading the taxonomy…'}>{(id, d) => <Select id={id} aria-describedby={d} value={category} onChange={(e) => setCategory(e.target.value)} options={categoryOptions(categories, item.proposed_category)} />}</Field>
        <Field label="Comment (optional)">{(id) => <Textarea id={id} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="e.g. Consumables for the die-casting cell are MRO" />}</Field>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Reason (optional)">{(id) => <Input id={id} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />}</Field>
          <Field label="Teach the classifier (optional)" hint="One word, 4-40 characters, added to the chosen category" error={kwOk ? undefined : 'A keyword is 4-40 characters'}>
            {(id, d) => <Input id={id} aria-describedby={d} value={keyword} maxLength={40} onChange={(e) => setKeyword(e.target.value)} />}
          </Field>
        </div>
      </div>
      {decide.error && <div className="mt-3"><ProblemBox error={decide.error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!kwOk} busy={decide.isPending} onClick={() => decide.mutate()}>
          {second ? 'Confirm category' : accepted ? 'Accept proposal' : parks ? 'Record first decision' : 'Reclassify'}
        </Button>
      </div>
    </Dialog>
  );
}

function BulkDialog({ ids, text, supplier, categories, onClose, onDone }: {
  ids: string[]; text: string; supplier: string; categories: TaxonomyNode[]; onClose: () => void; onDone: (r: BulkResult) => void;
}) {
  const bySelection = ids.length > 0;
  const [category, setCategory] = useState(categories[0]?.code ?? '');
  const [comment, setComment] = useState('');
  const [keyword, setKeyword] = useState('');
  const [reason, setReason] = useState('');
  const canByFilter = !!(text || supplier);
  const kwOk = !keyword.trim() || (keyword.trim().length >= 4 && keyword.trim().length <= 40);
  const ok = !!category && comment.trim().length >= 5 && kwOk && (bySelection || canByFilter);
  const run = useCommand(() => api.post<BulkResult>('/spend/classification-reviews/bulk', {
    category, comment: comment.trim(), reason: reason.trim() || undefined, learn_keyword: keyword.trim() || undefined,
    ...(bySelection ? { review_ids: ids } : { text: text || undefined, supplier: supplier || undefined }),
  }), { success: (r) => `${r.selected} review${r.selected === 1 ? '' : 's'} processed`, onSuccess: onDone });
  return (
    <Dialog open title="Bulk reclassify" onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">
        {bySelection ? `Decides the ${ids.length} selected review${ids.length === 1 ? '' : 's'}.`
          : canByFilter ? `Decides every open review matching ${[text && `description “${text}”`, supplier && `supplier ${supplier}`].filter(Boolean).join(' and ')} (at most the tenant bulk limit).`
            : 'Select rows in the queue, or filter by a description text or a supplier first: a bulk decision needs a selection.'}
        {' '}Each review is decided on its own with its own result; reviews at or above the four-eyes value are parked as the first of two decisions.
      </p>
      <div className="grid gap-3">
        <Field label="Category" required>{(id) => <Select id={id} value={category} onChange={(e) => setCategory(e.target.value)} options={categories.map((c) => ({ value: c.code, label: `${c.code} · ${c.name}` }))} />}</Field>
        <Field label="Comment" required hint="At least 5 characters; kept in the audit trail">{(id, d) => <Textarea id={id} aria-describedby={d} value={comment} onChange={(e) => setComment(e.target.value)} />}</Field>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Reason (optional)">{(id) => <Input id={id} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />}</Field>
          <Field label="Teach the classifier (optional)" hint="Learned once, from the first review that succeeds" error={kwOk ? undefined : 'A keyword is 4-40 characters'}>
            {(id, d) => <Input id={id} aria-describedby={d} value={keyword} maxLength={40} onChange={(e) => setKeyword(e.target.value)} />}
          </Field>
        </div>
      </div>
      {run.error && <div className="mt-3"><ProblemBox error={run.error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!ok} busy={run.isPending} onClick={() => run.mutate()}>Reclassify</Button>
      </div>
    </Dialog>
  );
}
