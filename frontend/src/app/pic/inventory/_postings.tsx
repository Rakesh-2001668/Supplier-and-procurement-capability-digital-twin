'use client';

import { useState } from 'react';
import { Button, DataTable, Dialog, Field, Input, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, inr, label, qty } from '@/lib/pic/format';
import { useApi, useCommand, useList } from '@/lib/pic/hooks';
import { useSessionUser } from '../invoices/_components';
import {
  CheckFilter, FilterBar, Flag, isQty, MaterialInput, PlantSelect, postingHref, qs, ReasonDialog, SelectFilter, SlocInput, StockRow, TextFilter, today, UserRef,
  useDebounced, usePlants, useRules,
} from './_shared';

export type PostingSummary = {
  id: string; number: string; type: string; status: string; plant: string; companyCode: string; postingDate: string; reasonCode: string | null; reason: string | null;
  totalValueMinor: number | null; autoPosted: boolean; erpDocument: string | null; createdAt: string | null; postedAt: string | null; rowVersion: number;
};
export type PostingLine = {
  lineNo: number; material: string; description: string; uom: string; batch: string; qty: string; fromPlant: string; fromStorageLocation: string; fromStockType: string;
  toPlant: string | null; toStorageLocation: string | null; toStockType: string | null; movementType: string; unitPriceMinor: number | null; valueMinor: number | null;
};
export type ApprovalStep = {
  role: string; sequence: number; status: string; decision: string | null; comment: string | null; dueAt: string | null; decidedAt: string | null;
  decidedBy: string | null; taskId: string;
};
export type PostingDetail = PostingSummary & {
  rule: string | null; decisionComment: string | null; createdBy: UserRef; submittedBy: UserRef; approvedBy: UserRef; postedBy: UserRef;
  submittedAt: string | null; approvedAt: string | null; lines: PostingLine[]; approvals: ApprovalStep[];
  movements: { movementType: string; plant: string; storageLocation: string; stockType: string; batch: string; qty: string; valueMinor: number | null; material: string | null }[];
  warnings: { code: string; line: number; material: string; detail: string }[];
};

export const POSTING_TYPES = ['TRANSFER', 'BLOCK', 'UNBLOCK', 'SCRAP'];
const TYPE_TEXT: Record<string, string> = {
  TRANSFER: 'Transfer (between locations or plants)', BLOCK: 'Block (unrestricted to blocked)', UNBLOCK: 'Unblock (blocked to unrestricted)', SCRAP: 'Scrap (write off)',
};

// ---------------------------------------------------------------- list
export function PostingsTab({ canPost }: { canPost: boolean }) {
  const rules = useRules();
  const [plant, setPlant] = useState('');
  const [f, setF] = useState({ status: '', type: '', q: '', mine: false });
  const set = (patch: Partial<typeof f>) => setF((x) => ({ ...x, ...patch }));
  const d = useDebounced(f);
  const [creating, setCreating] = useState(false);
  const list = useList<PostingSummary>(`/stock-postings${qs({ plant, status: d.status, type: d.type, q: d.q.trim(), mine: d.mine })}`);
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-3xl text-sm text-slate-600">
          Transfers, blocks, unblocks and scrap. Small transfers, blocks and unblocks post at once; scrap and larger values go to approval by value band. The person who
          raised a posting never approves it (SOD-10).
        </p>
        {canPost && <Button variant="primary" onClick={() => setCreating(true)}>New stock posting</Button>}
      </div>
      <FilterBar name="Filter stock postings">
        <SelectFilter label="Status" value={f.status} onChange={(status) => set({ status })}
          options={[{ value: '', label: 'All statuses' }, ...(rules.data?.enums.postingStatuses ?? []).map((s) => ({ value: s, label: label(s) }))]} />
        <SelectFilter label="Type" value={f.type} onChange={(type) => set({ type })}
          options={[{ value: '', label: 'All types' }, ...POSTING_TYPES.map((t) => ({ value: t, label: label(t) }))]} />
        <PlantSelect value={plant} onChange={setPlant} />
        <TextFilter label="Posting number" value={f.q} onChange={(q) => set({ q })} placeholder="e.g. STP-10" />
        <CheckFilter label="Raised by me" checked={f.mine} onChange={(mine) => set({ mine })} />
      </FilterBar>
      <DataTable<PostingSummary>
        caption="Stock postings" rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
        loadingMore={list.isFetchingNextPage} rowHref={(p) => postingHref(p.number)} empty="No stock postings match these filters"
        columns={[
          { key: 'number', header: 'Posting' },
          { key: 'type', header: 'Type', render: (p) => label(p.type) },
          { key: 'plant', header: 'Plant' },
          { key: 'status', header: 'Status', render: (p) => (
            <div className="space-y-1"><StatusChip status={p.status} />{p.autoPosted && <p><Flag tone="muted">Posted automatically</Flag></p>}</div>
          ) },
          { key: 'totalValueMinor', header: 'Value', align: 'right', render: (p) => inr(p.totalValueMinor) },
          { key: 'reason', header: 'Reason', render: (p) => <span title={p.reason ?? undefined}>{p.reasonCode ?? '–'}</span> },
          { key: 'postingDate', header: 'Posting date', render: (p) => date(p.postingDate) },
          { key: 'erpDocument', header: 'ERP document', render: (p) => p.erpDocument ?? '–' },
        ]}
      />
      {creating && <CreatePostingDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

// ---------------------------------------------------------------- create
type Line = { key: number; material: string; batch: string; sloc: string; stockType: string; qty: string; toSloc: string; toPlant: string };
let nextKey = 1;
const emptyLine = (sloc = ''): Line => ({ key: nextKey++, material: '', batch: '', sloc, stockType: 'UNRESTRICTED', qty: '', toSloc: '', toPlant: '' });

/** The stock the line takes from, so the user sees what exists before the server checks it. */
export function StockHint({ material, plant, type }: { material: string; plant: string; type: string }) {
  const wanted = material.trim();
  const stock = useApi<{ items: StockRow[] }>(wanted.length >= 3 && plant ? `/stock${qs({ material: wanted, plant, limit: 50 })}` : null);
  const rows = (stock.data?.items ?? []).filter((r) => r.material === wanted && (type === 'BLOCK' ? r.stockType === 'UNRESTRICTED' : type === 'UNBLOCK' ? r.stockType === 'BLOCKED' : true));
  if (!wanted || !stock.data) return null;
  if (!rows.length) return <p className="text-xs text-amber-700">No matching stock at {plant}. The server will refuse the quantity.</p>;
  return (
    <p className="text-xs text-slate-600">
      On hand at {plant}: {rows.slice(0, 5).map((r) => `${r.storageLocation} ${label(r.stockType).toLowerCase()}${r.batch ? ` lot ${r.batch}` : ''} ${qty(r.qty, r.uom)}`).join(' · ')}
      {rows.length > 5 ? ` · and ${rows.length - 5} more` : ''}
    </p>
  );
}

export function CreatePostingDialog({ onClose }: { onClose: () => void }) {
  const rules = useRules();
  const { plants } = usePlants();
  const [type, setType] = useState('TRANSFER');
  const [plantChoice, setPlant] = useState('');
  const plant = plantChoice || plants[0]?.code || '';
  const [postingDate, setPostingDate] = useState(today());
  const [reasonCode, setReasonCode] = useState('');
  const [reason, setReason] = useState('');
  const [submit, setSubmit] = useState(true);
  const [lines, setLines] = useState<Line[]>(() => [emptyLine()]);
  const body = rules.data?.posting.body;
  const update = (key: number, patch: Partial<Line>) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  const reasons = type === 'SCRAP' ? body?.scrapReasons : type === 'BLOCK' ? body?.blockReasons : undefined;
  const needsReason = !!body?.reasonRequiredFor.includes(type);
  const transfer = type === 'TRANSFER';
  const takesType = transfer || type === 'SCRAP';

  const problem = !plant ? 'Choose the plant'
    : type === 'SCRAP' && !reasonCode ? 'A scrap needs a reason code'
      : needsReason && reason.trim().length < 3 ? `A ${type.toLowerCase()} needs a reason (at least 3 characters)`
        : lines.some((l) => !l.material.trim() || !l.sloc.trim() || !isQty(l.qty)) ? 'Every line needs a material, a storage location and a positive quantity'
          : transfer && lines.some((l) => !l.toSloc.trim()) ? 'Every transfer line needs the target storage location'
            : body && lines.length > body.maxLines ? `At most ${body.maxLines} lines per posting` : null;

  const create = useCommand(() => api.post<PostingDetail>('/stock-postings', {
    type, plant, reasonCode: reasonCode || undefined, reason: reason.trim() || undefined, postingDate: postingDate || undefined, submit,
    lines: lines.map((l) => ({
      material: l.material.trim(), qty: l.qty.trim(), batch: l.batch.trim(), storageLocation: l.sloc.trim(),
      stockType: takesType ? l.stockType : undefined, toStorageLocation: transfer ? l.toSloc.trim() : undefined, toPlant: transfer && l.toPlant ? l.toPlant : undefined,
    })),
  }), {
    success: (r) => `${r.number} ${r.status === 'POSTED' ? (r.autoPosted ? 'posted automatically' : 'posted') : r.status === 'SUBMITTED' ? 'submitted, awaiting approval' : label(r.status).toLowerCase()}`,
    onSuccess: onClose,
  });

  return (
    <Dialog open wide title="New stock posting" onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Type" required>{(id) => <Select id={id} value={type} onChange={(e) => { setType(e.target.value); setReasonCode(''); }} options={POSTING_TYPES.map((t) => ({ value: t, label: TYPE_TEXT[t] }))} />}</Field>
        <Field label="Plant (stock leaves)" required>
          {(id) => <Select id={id} value={plant} onChange={(e) => setPlant(e.target.value)} options={plants.map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))} />}
        </Field>
        <Field label="Posting date" hint="Not in the future; must be in an open period">{(id, by) => <Input id={id} aria-describedby={by} type="date" max={today()} value={postingDate} onChange={(e) => setPostingDate(e.target.value)} />}</Field>
        {reasons && (
          <Field label="Reason code" required={type === 'SCRAP'}>
            {(id) => <Select id={id} value={reasonCode} onChange={(e) => setReasonCode(e.target.value)}
              options={[{ value: '', label: type === 'SCRAP' ? 'Choose a reason code' : 'No reason code' }, ...Object.entries(reasons).map(([code, text]) => ({ value: code, label: `${code} · ${text}` }))]} />}
          </Field>
        )}
        <div className={reasons ? 'md:col-span-2' : 'md:col-span-3'}>
          <Field label="Reason" required={needsReason}>{(id) => <Textarea id={id} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
        </div>
      </div>

      <fieldset className="mt-4 space-y-3">
        <legend className="text-sm font-semibold text-slate-900">Lines</legend>
        {lines.map((l, i) => (
          <div key={l.key} className="rounded-lg border border-slate-200 p-3">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Line {i + 1}</p>
              {lines.length > 1 && <Button variant="ghost" aria-label={`Remove line ${i + 1}`} onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}>Remove</Button>}
            </div>
            <div className="grid gap-3 md:grid-cols-4">
              <div className="md:col-span-2"><MaterialInput value={l.material} onChange={(material) => update(l.key, { material })} required /></div>
              <Field label="Batch / lot" hint="Needed when the stock is held by lot">{(id, by) => <Input id={id} aria-describedby={by} value={l.batch} onChange={(e) => update(l.key, { batch: e.target.value })} />}</Field>
              <Field label="Quantity" required>{(id) => <Input id={id} inputMode="decimal" value={l.qty} onChange={(e) => update(l.key, { qty: e.target.value })} />}</Field>
              <SlocInput plant={plant} name={transfer ? 'From storage location' : 'Storage location'} value={l.sloc} onChange={(sloc) => update(l.key, { sloc })} required />
              {takesType && (
                <Field label="Stock type taken">
                  {(id) => <Select id={id} value={l.stockType} onChange={(e) => update(l.key, { stockType: e.target.value })} options={[{ value: 'UNRESTRICTED', label: 'Unrestricted' }, { value: 'BLOCKED', label: 'Blocked' }]} />}
                </Field>
              )}
              {transfer && (
                <>
                  <SlocInput plant={l.toPlant || plant} name="To storage location" value={l.toSloc} onChange={(toSloc) => update(l.key, { toSloc })} required />
                  {body?.crossPlantTransfer && (
                    <Field label="To plant" hint="Empty: same plant">
                      {(id, by) => <Select id={id} aria-describedby={by} value={l.toPlant} onChange={(e) => update(l.key, { toPlant: e.target.value })}
                        options={[{ value: '', label: 'Same plant' }, ...plants.filter((p) => p.code !== plant).map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))]} />}
                    </Field>
                  )}
                </>
              )}
            </div>
            <div className="mt-2"><StockHint material={l.material} plant={plant} type={type} /></div>
          </div>
        ))}
        <Button onClick={() => setLines((ls) => [...ls, emptyLine(ls[ls.length - 1]?.sloc ?? '')])}>Add line</Button>
      </fieldset>

      <label className="mt-4 flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5 h-4 w-4" checked={submit} onChange={(e) => setSubmit(e.target.checked)} />
        <span>Submit now: a posting under {inr(body?.autoPostBelowMinor ?? null)} of type {(body?.autoPostTypes ?? []).map((t) => label(t).toLowerCase()).join(', ')} posts at once, anything else goes to approval.
          Leave unticked to save a draft.</span>
      </label>
      {problem && <p className="mt-2 text-xs text-amber-700" role="status">{problem}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!!problem} busy={create.isPending} onClick={() => create.mutate()}>{submit ? 'Create and submit' : 'Save draft'}</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- actions on one posting
export function PostingActions({ posting }: { posting: PostingDetail }) {
  const user = useSessionUser();
  const rules = useRules();
  const me = rules.data?.me;
  const [dialog, setDialog] = useState<'approve' | 'reject' | 'cancel' | null>(null);
  const base = `/stock-postings/${encodeURIComponent(posting.number)}`;
  const done = () => setDialog(null);
  const result = (r: PostingDetail) => `${r.number} ${label(r.status).toLowerCase()}`;
  const submit = useCommand(() => api.post<PostingDetail>(`${base}/submit`), { success: result });
  const post = useCommand(() => api.post<PostingDetail>(`${base}/post`), { success: result });
  const approve = useCommand((comment: string) => api.post<PostingDetail>(`${base}/approve`, { comment: comment || undefined }), { success: result, onSuccess: done });
  const reject = useCommand((reason: string) => api.post<PostingDetail>(`${base}/reject`, { reason }), { success: result, onSuccess: done });
  const cancel = useCommand((reason: string) => api.post<PostingDetail>(`${base}/cancel`, { reason }), { success: result, onSuccess: done });
  if (!me) return null;
  const isMaker = !!user && (posting.createdBy?.id === user.id || posting.submittedBy?.id === user.id);
  const s = posting.status;
  const canCancel = me.canPost && ['DRAFT', 'SUBMITTED', 'APPROVED'].includes(s);
  const makerNote = 'You raised or submitted this posting, so you cannot approve or reject it (SOD-10). A second inventory controller decides.';
  return (
    <>
      {s === 'DRAFT' && me.canPost && <Button variant="primary" busy={submit.isPending} onClick={() => submit.mutate()}>Submit</Button>}
      {s === 'SUBMITTED' && me.canApprove && (
        <>
          <Button variant="primary" disabled={isMaker} title={isMaker ? makerNote : undefined} aria-describedby={isMaker ? 'sod-note' : undefined} onClick={() => setDialog('approve')}>Approve</Button>
          <Button variant="danger" disabled={isMaker} title={isMaker ? makerNote : undefined} aria-describedby={isMaker ? 'sod-note' : undefined} onClick={() => setDialog('reject')}>Reject</Button>
        </>
      )}
      {s === 'APPROVED' && me.canPost && <Button variant="primary" busy={post.isPending} onClick={() => post.mutate()}>Post to stock</Button>}
      {canCancel && <Button variant="danger" onClick={() => setDialog('cancel')}>Cancel posting</Button>}
      {s === 'SUBMITTED' && me.canApprove && isMaker && <p id="sod-note" className="basis-full text-right text-xs text-amber-800" role="note">{makerNote}</p>}
      {dialog === 'approve' && <ReasonDialog title={`Approve ${posting.number}`} fieldLabel="Comment" required={false} confirm="Approve" busy={approve.isPending}
        intro={<>Approving a posting of {inr(posting.totalValueMinor)} lets it be posted to stock. The server checks that you are not the maker.</>} onConfirm={(t) => approve.mutate(t)} onClose={() => setDialog(null)} />}
      {dialog === 'reject' && <ReasonDialog title={`Reject ${posting.number}`} fieldLabel="Reason for rejecting" required confirm="Reject posting" variant="danger" busy={reject.isPending}
        onConfirm={(t) => reject.mutate(t)} onClose={() => setDialog(null)} />}
      {dialog === 'cancel' && <ReasonDialog title={`Cancel ${posting.number}`} fieldLabel="Reason for cancelling" required confirm="Cancel posting" variant="danger" busy={cancel.isPending}
        intro="A cancelled posting never reaches stock." onConfirm={(t) => cancel.mutate(t)} onClose={() => setDialog(null)} />}
    </>
  );
}
