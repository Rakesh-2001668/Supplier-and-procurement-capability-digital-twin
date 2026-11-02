'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, DataTable, Dialog, Field, Input, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, inr, label, qty } from '@/lib/pic/format';
import { useCommand, useList } from '@/lib/pic/hooks';
import { useSessionUser } from '../invoices/_components';
import {
  ApprovalStep,
} from './_postings';
import {
  countHref, Flag, materialHref, MaterialInput, PlantSelect, qs, ReasonDialog, SelectFilter, signedInr, signedQty, SlocInput, FilterBar, TextFilter, UserRef,
  useRules,
} from './_shared';

export type CountSummary = {
  id: string; number: string; status: string; plant: string; companyCode: string; storageLocation: string; materialGroup: string | null;
  scope: { materials: string[]; abc: string[]; materialGroup: string | null }; description: string | null; plannedDate: string | null; frozenAt: string;
  lineCount: number; erpDocument: string | null; createdAt: string | null; postedAt: string | null; rowVersion: number; blind: boolean;
  gainMinor?: number | null; lossMinor?: number | null; accuracyPct?: string | null;
};
export type CountLine = {
  lineNo: number; material: string; description: string; uom: string; batch: string; stockType: string; unlisted: boolean; countStatus: string;
  countedQty: string | null; countedBy: UserRef; countedAt: string | null; recountQty: string | null; recountedBy: UserRef; recountReason: string | null;
  finalQty: string | null; note: string | null;
  // present only when the server reveals the book quantities (approvers and controllers who did not count)
  bookQty?: string; unitPriceMinor?: number | null; diffQty?: string | null; diffValueMinor?: number | null; firstCountWithinTolerance?: boolean | null;
  postedQty?: string | null; driftQty?: string | null;
};
export type CountDetail = CountSummary & {
  rule: string | null; decisionComment: string | null; createdBy: UserRef; submittedBy: UserRef; approvedBy: UserRef; postedBy: UserRef; submittedAt: string | null;
  progress: { lines: number; counted: number; recountRequired: number; accepted: number }; lines: CountLine[]; approvals: ApprovalStep[];
};

const COUNT_STATUS_FALLBACK = ['PLANNED', 'COUNTING', 'COUNTED', 'PENDING_APPROVAL', 'APPROVED', 'POSTED', 'CANCELLED'];

export function scopeText(scope: CountSummary['scope'], group: string | null): string {
  const parts = [group && `group ${group}`, scope?.abc?.length ? `ABC ${scope.abc.join('/')}` : null, scope?.materials?.length ? `${scope.materials.length} named material(s)` : null].filter(Boolean);
  return parts.length ? parts.join(' · ') : 'Whole location';
}

// ---------------------------------------------------------------- list
export function CountsTab({ canCreate }: { canCreate: boolean }) {
  const rules = useRules();
  const [plant, setPlant] = useState('');
  const [status, setStatus] = useState('');
  const [sloc, setSloc] = useState('');
  const [creating, setCreating] = useState(false);
  const list = useList<CountSummary>(`/physical-inventories${qs({ plant, status, storage_location: sloc.trim() })}`);
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-3xl text-sm text-slate-600">
          Blind cycle counts: the book quantity is frozen when the count is created and hidden from counters. Lines outside the tolerance are recounted by someone
          else; the controller approves the differences (never a counter, SOD-11) and posts them.
        </p>
        {canCreate && <Button variant="primary" onClick={() => setCreating(true)}>New physical inventory</Button>}
      </div>
      <FilterBar name="Filter counts">
        <SelectFilter label="Status" value={status} onChange={setStatus}
          options={[{ value: '', label: 'All statuses' }, ...(rules.data?.enums.countStatuses ?? COUNT_STATUS_FALLBACK).map((s) => ({ value: s, label: label(s) }))]} />
        <PlantSelect value={plant} onChange={setPlant} />
        <TextFilter label="Storage location" value={sloc} onChange={setSloc} />
      </FilterBar>
      <DataTable<CountSummary>
        caption="Physical inventory documents" rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
        loadingMore={list.isFetchingNextPage} rowHref={(c) => countHref(c.number)} empty="No physical inventory documents match these filters"
        columns={[
          { key: 'number', header: 'Count' },
          { key: 'status', header: 'Status', render: (c) => <StatusChip status={c.status} /> },
          { key: 'location', header: 'Plant / location', render: (c) => `${c.plant} / ${c.storageLocation}` },
          { key: 'scope', header: 'Scope', render: (c) => <span title={c.description ?? undefined}>{scopeText(c.scope, c.materialGroup)}</span> },
          { key: 'lineCount', header: 'Lines', align: 'right' },
          { key: 'plannedDate', header: 'Planned', render: (c) => date(c.plannedDate) },
          { key: 'frozenAt', header: 'Frozen', render: (c) => dateTime(c.frozenAt) },
          { key: 'result', header: 'Result', render: (c) => c.blind ? <Flag tone="muted">Blind count</Flag> : (
            <div className="text-xs"><p>Gain {inr(c.gainMinor ?? 0)} · loss {inr(c.lossMinor ?? 0)}</p>{c.accuracyPct && <p>Accuracy {c.accuracyPct}%</p>}</div>
          ) },
        ]}
      />
      {creating && <CreateCountDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

// ---------------------------------------------------------------- create
export function CreateCountDialog({ onClose }: { onClose: () => void }) {
  const [plant, setPlant] = useState('');
  const [sloc, setSloc] = useState('');
  const [group, setGroup] = useState('');
  const [abc, setAbc] = useState<string[]>([]);
  const [materials, setMaterials] = useState('');
  const [description, setDescription] = useState('');
  const [planned, setPlanned] = useState('');
  const named = materials.split(/[\s,;]+/).map((m) => m.trim()).filter(Boolean);
  const problem = !plant ? 'Choose the plant' : !sloc.trim() ? 'Enter the storage location to count' : null;
  const create = useCommand(() => api.post<CountDetail>('/physical-inventories', {
    plant, storageLocation: sloc.trim(), materialGroup: group.trim() || undefined, abc: abc.length ? abc : undefined, materials: named.length ? named : undefined,
    description: description.trim() || undefined, plannedDate: planned || undefined,
  }), { success: (r) => `${r.number} created with ${r.lineCount} lines; book quantities are frozen`, onSuccess: onClose });
  return (
    <Dialog open title="New physical inventory" onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <PlantSelect value={plant} onChange={setPlant} all={false} required />
        <SlocInput plant={plant} value={sloc} onChange={setSloc} required hint="Unrestricted stock of this location is counted" />
        <TextFilter label="Material group (optional)" value={group} onChange={setGroup} />
        <fieldset className="flex flex-col gap-1">
          <legend className="text-xs font-medium text-slate-700">ABC class (by value issued, last 12 months)</legend>
          <div className="flex gap-4 pt-1.5">
            {['A', 'B', 'C'].map((c) => (
              <label key={c} className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" className="h-4 w-4 accent-[#1A56DB]" checked={abc.includes(c)} onChange={(e) => setAbc((cur) => (e.target.checked ? [...cur, c] : cur.filter((x) => x !== c)))} />
                Class {c}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="md:col-span-2">
          <Field label="Named materials (optional)" hint={named.length ? `${named.length} material(s)` : 'Material numbers separated by commas or spaces; empty: every material matching the filters above'}>
            {(id, by) => <Textarea id={id} aria-describedby={by} value={materials} onChange={(e) => setMaterials(e.target.value)} className="font-mono text-xs" />}
          </Field>
        </div>
        <TextFilter label="Description" value={description} onChange={setDescription} placeholder="e.g. Quarterly cycle count" />
        <TextFilter label="Planned date" type="date" value={planned} onChange={setPlanned} />
      </div>
      <p className="mt-3 text-xs text-slate-500">Creating the count freezes the book quantity of every selected line. Stock moves after the freeze are not lost: the posted difference is relative to the freeze.</p>
      {problem && <p className="mt-2 text-xs text-amber-700" role="status">{problem}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!!problem} busy={create.isPending} onClick={() => create.mutate()}>Create count</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- count entry (blind) and read-only blind list
type Draft = { qty: string; note: string };
type Extra = { material: string; batch: string; qty: string };
const lineKey = (l: CountLine) => `${l.material}|${l.batch}`;

export function CountEntry({ count, editable }: { count: CountDetail; editable: boolean }) {
  const user = useSessionUser();
  const rules = useRules();
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [extras, setExtras] = useState<Extra[]>([]);
  const [extra, setExtra] = useState<Extra>({ material: '', batch: '', qty: '' });
  const sameCounter = rules.data?.count.body.recountDifferentCounter ?? true;
  const me = user?.id;

  /** Whether this user may enter this line now (the server decides again). */
  function lockReason(l: CountLine): string | null {
    if (!editable) return null;
    if (l.countStatus === 'COUNTED' && l.countedBy && l.countedBy.id !== me) return `Counted by ${l.countedBy.name}; only the counter corrects it`;
    if (l.countStatus === 'RECOUNT_REQUIRED' && sameCounter && l.countedBy && l.countedBy.id === me) return 'Outside the tolerance: someone other than the first counter recounts it';
    if (l.countStatus === 'RECOUNTED' && l.recountedBy && l.recountedBy.id !== me) return `Recounted by ${l.recountedBy.name}`;
    return null;
  }
  const shown = (l: CountLine) => (l.countStatus === 'RECOUNT_REQUIRED' ? '' : (l.countStatus === 'RECOUNTED' ? l.recountQty : l.countedQty) ?? '');
  const entries = [
    ...count.lines.filter((l) => drafts[lineKey(l)] && drafts[lineKey(l)].qty.trim() !== '').map((l) => ({ material: l.material, batch: l.batch, qty: drafts[lineKey(l)].qty.trim(), note: drafts[lineKey(l)].note.trim() || undefined })),
    ...extras.map((x) => ({ material: x.material.trim(), batch: x.batch.trim(), qty: x.qty.trim(), note: 'Found stock, not on the list' })),
  ];
  const invalid = entries.some((e) => !Number.isFinite(Number(e.qty)) || Number(e.qty) < 0);
  const save = useCommand(() => api.put<CountDetail>(`/physical-inventories/${encodeURIComponent(count.number)}/counts`, { counts: entries }), {
    success: (r) => `${entries.length} count(s) saved · ${r.progress.accepted} of ${r.progress.lines} lines accepted${r.progress.recountRequired ? ` · ${r.progress.recountRequired} need a recount` : ''}`,
    onSuccess: () => { setDrafts({}); setExtras([]); },
  });
  const setDraft = (l: CountLine, patch: Partial<Draft>) => setDrafts((d) => ({ ...d, [lineKey(l)]: { qty: d[lineKey(l)]?.qty ?? '', note: d[lineKey(l)]?.note ?? '', ...patch } }));

  return (
    <div className="space-y-4">
      <div role="note" className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
        <p className="font-semibold">Blind count</p>
        <p>The book quantity is not shown. Count what is on the shelf and enter it. A line outside the tolerance
          ({rules.data ? `${rules.data.count.body.qtyTolerancePct}% and ${inr(rules.data.count.body.valueToleranceMinor)}` : 'rule INVENTORY-COUNT'}) is recounted by another counter.</p>
      </div>
      <p className="text-sm text-slate-700" role="status">
        {count.progress.counted} of {count.progress.lines} lines counted · {count.progress.accepted} accepted{count.progress.recountRequired ? ` · ${count.progress.recountRequired} need a recount` : ''}
      </p>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <caption className="sr-only">Lines to count</caption>
          <thead className="bg-slate-50">
            <tr>{['Line', 'Material', 'Lot', 'Status', editable ? 'Counted quantity' : 'Counted', 'Counted by', ...(editable ? ['Note'] : [])].map((h) => (
              <th key={h} scope="col" className="whitespace-nowrap px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">{h}</th>))}</tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {count.lines.map((l) => {
              const lock = lockReason(l);
              const key = lineKey(l);
              return (
                <tr key={l.lineNo} className="align-top">
                  <td className="px-3 py-2">{l.lineNo}</td>
                  <td className="px-3 py-2"><Link prefetch={false} className="font-medium text-[#1A56DB] hover:underline" href={materialHref(l.material)}>{l.material}</Link><p className="text-xs text-slate-500">{l.description} · {l.uom}</p>
                    {l.unlisted && <Flag tone="info">Found stock, not on the list</Flag>}</td>
                  <td className="px-3 py-2">{l.batch || '–'}</td>
                  <td className="px-3 py-2"><StatusChip status={l.countStatus} />
                    {l.countStatus === 'RECOUNT_REQUIRED' && <p className="mt-1 max-w-[14rem] text-xs text-amber-800">Recount needed{l.recountReason ? `: ${l.recountReason}` : ''}</p>}</td>
                  <td className="px-3 py-2">
                    {editable ? (
                      <Input aria-label={`Counted quantity for ${l.material}${l.batch ? ` lot ${l.batch}` : ''} (${l.uom})`} inputMode="decimal" className="w-28" disabled={!!lock} title={lock ?? undefined}
                        value={drafts[key]?.qty ?? shown(l)} onChange={(e) => setDraft(l, { qty: e.target.value })} />
                    ) : qty(l.finalQty ?? l.countedQty, l.uom)}
                    {lock && <p className="mt-1 max-w-[14rem] text-xs text-slate-600">{lock}</p>}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600">{(l.recountedBy ?? l.countedBy)?.name ?? '–'}</td>
                  {editable && <td className="px-3 py-2"><Input aria-label={`Note for ${l.material}`} maxLength={500} className="w-40" disabled={!!lock} value={drafts[key]?.note ?? l.note ?? ''} onChange={(e) => setDraft(l, { note: e.target.value })} /></td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {editable && (
        <>
          <fieldset className="rounded-lg border border-slate-200 p-3">
            <legend className="px-1 text-xs font-semibold text-slate-700">Found stock that is not on the list</legend>
            <div className="grid gap-3 md:grid-cols-4">
              <div className="md:col-span-2"><MaterialInput value={extra.material} onChange={(material) => setExtra((x) => ({ ...x, material }))} /></div>
              <TextFilter label="Lot" value={extra.batch} onChange={(batch) => setExtra((x) => ({ ...x, batch }))} />
              <TextFilter label="Counted quantity" value={extra.qty} onChange={(q) => setExtra((x) => ({ ...x, qty: q }))} />
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <Button disabled={!extra.material.trim() || !(extra.qty.trim() !== '' && Number(extra.qty) >= 0)} onClick={() => { setExtras((xs) => [...xs, extra]); setExtra({ material: '', batch: '', qty: '' }); }}>Add found stock</Button>
              {extras.length > 0 && <p className="text-xs text-slate-600">{extras.map((x) => `${x.material}${x.batch ? `/${x.batch}` : ''} × ${x.qty}`).join(', ')} will be saved with the counts</p>}
            </div>
          </fieldset>
          <div className="flex flex-wrap items-center justify-end gap-3">
            {invalid && <p className="text-xs text-amber-700" role="status">Counted quantities are zero or more.</p>}
            <p className="text-xs text-slate-500">{entries.length} line(s) to save</p>
            <Button variant="primary" disabled={!entries.length || invalid} busy={save.isPending} onClick={() => save.mutate()}>Save counts</Button>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- variance view (approvers and controllers)
export function VarianceTable({ count }: { count: CountDetail }) {
  const rows = count.lines.map((l) => ({ ...l, id: String(l.lineNo) }));
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">Book quantity is as at the freeze ({dateTime(count.frozenAt)}). The difference posted is the counted quantity minus the book quantity at the freeze; stock that moved since is not double-counted.</p>
      <DataTable<(typeof rows)[number]>
        caption="Count variances" rows={rows} empty="No lines"
        columns={[
          { key: 'lineNo', header: 'Line' },
          { key: 'material', header: 'Material', render: (l) => (
            <div><Link prefetch={false} className="font-medium text-[#1A56DB] hover:underline" href={materialHref(l.material)}>{l.material}</Link>
              <p className="text-xs text-slate-500">{l.description}</p>{l.unlisted && <Flag tone="info">Found stock, not on the list</Flag>}</div>
          ) },
          { key: 'batch', header: 'Lot', render: (l) => l.batch || '–' },
          { key: 'bookQty', header: 'Book', align: 'right', render: (l) => qty(l.bookQty, l.uom) },
          { key: 'countedQty', header: 'Counted', align: 'right', render: (l) => qty(l.countedQty, l.uom) },
          { key: 'recountQty', header: 'Recount', align: 'right', render: (l) => l.recountQty !== null ? qty(l.recountQty, l.uom) : '–' },
          { key: 'finalQty', header: 'Accepted', align: 'right', render: (l) => qty(l.finalQty, l.uom) },
          { key: 'diffQty', header: 'Difference', align: 'right', render: (l) => l.diffQty === null || l.diffQty === undefined ? '–'
            : <span className={Number(l.diffQty) ? 'font-semibold' : ''}>{signedQty(l.diffQty, l.uom)}{Number(l.diffQty) > 0 ? ' (gain)' : Number(l.diffQty) < 0 ? ' (loss)' : ''}</span> },
          { key: 'diffValueMinor', header: 'Value', align: 'right', render: (l) => signedInr(l.diffValueMinor) },
          { key: 'countStatus', header: 'Status', render: (l) => (
            <div className="space-y-1"><StatusChip status={l.countStatus} />
              {l.firstCountWithinTolerance === false && <p><Flag tone="warn">First count outside tolerance</Flag></p>}
              {l.recountReason && <p className="max-w-[14rem] text-xs text-slate-600">{l.recountReason}</p>}</div>
          ) },
          { key: 'by', header: 'Counted by', render: (l) => <span className="text-xs">{[l.countedBy?.name, l.recountedBy && `recount ${l.recountedBy.name}`].filter(Boolean).join(' · ') || '–'}</span> },
          ...(count.status === 'POSTED' ? [{ key: 'posted', header: 'Posted', align: 'right' as const, render: (l: CountLine) => <span>{signedQty(l.postedQty)}{Number(l.driftQty) ? <span className="block text-xs text-slate-500">stock moved {signedQty(l.driftQty)} since freeze</span> : null}</span> }] : []),
        ]}
      />
    </div>
  );
}

// ---------------------------------------------------------------- actions on one count
export function CountActions({ count }: { count: CountDetail }) {
  const rules = useRules();
  const me = rules.data?.me;
  const [dialog, setDialog] = useState<'approve' | 'reject' | 'recount' | 'cancel' | null>(null);
  const base = `/physical-inventories/${encodeURIComponent(count.number)}`;
  const result = (r: CountDetail) => `${r.number} ${label(r.status).toLowerCase()}`;
  const done = () => setDialog(null);
  const submit = useCommand(() => api.post<CountDetail>(`${base}/submit`), { success: result });
  const post = useCommand(() => api.post<CountDetail>(`${base}/post`), { success: (r) => `${result(r)} · differences posted to stock` });
  const approve = useCommand((comment: string) => api.post<CountDetail>(`${base}/approve`, { comment: comment || undefined }), { success: result, onSuccess: done });
  const reject = useCommand((reason: string) => api.post<CountDetail>(`${base}/reject`, { reason }), { success: (r) => `${result(r)}; sent back to the counters`, onSuccess: done });
  const cancel = useCommand((reason: string) => api.post<CountDetail>(`${base}/cancel`, { reason }), { success: result, onSuccess: done });
  const recount = useCommand((args: { reason: string; materials: string[] }) => api.post<CountDetail>(`${base}/recount`, { reason: args.reason, materials: args.materials.length ? args.materials : undefined }),
    { success: (r) => `${r.number}: recount requested`, onSuccess: done });
  if (!me) return null;
  const s = count.status;
  // A counter (blind view) never approves: SOD-11. The server refuses it too.
  const counter = count.blind && me.canApprove;
  const sodNote = 'You counted on this document, so you cannot approve or reject its differences (SOD-11). Another controller decides.';
  return (
    <>
      {s === 'COUNTED' && (me.canPost || me.canCount) && <Button variant="primary" busy={submit.isPending} onClick={() => submit.mutate()}>Submit for approval</Button>}
      {['COUNTING', 'COUNTED', 'PENDING_APPROVAL'].includes(s) && (me.canPost || me.canApprove) && <Button onClick={() => setDialog('recount')}>Request recount</Button>}
      {s === 'PENDING_APPROVAL' && me.canApprove && (
        <>
          <Button variant="primary" disabled={counter} title={counter ? sodNote : undefined} aria-describedby={counter ? 'sod-note' : undefined} onClick={() => setDialog('approve')}>Approve differences</Button>
          <Button variant="danger" disabled={counter} title={counter ? sodNote : undefined} aria-describedby={counter ? 'sod-note' : undefined} onClick={() => setDialog('reject')}>Send back</Button>
        </>
      )}
      {s === 'APPROVED' && me.canPost && <Button variant="primary" busy={post.isPending} onClick={() => post.mutate()}>Post differences</Button>}
      {!['POSTED', 'CANCELLED'].includes(s) && (me.canPost || me.canCount) && <Button variant="danger" onClick={() => setDialog('cancel')}>Cancel count</Button>}
      {s === 'PENDING_APPROVAL' && me.canApprove && counter && <p id="sod-note" className="basis-full text-right text-xs text-amber-800" role="note">{sodNote}</p>}
      {dialog === 'approve' && <ReasonDialog title={`Approve ${count.number}`} fieldLabel="Comment" required={false} confirm="Approve" busy={approve.isPending}
        intro={<>Approving accepts the counted quantities (gain {inr(count.gainMinor ?? 0)}, loss {inr(count.lossMinor ?? 0)}). Posting follows as a separate step.</>}
        onConfirm={(t) => approve.mutate(t)} onClose={() => setDialog(null)} />}
      {dialog === 'reject' && <ReasonDialog title={`Send ${count.number} back`} fieldLabel="Reason" required confirm="Send back to counters" variant="danger" busy={reject.isPending}
        onConfirm={(t) => reject.mutate(t)} onClose={() => setDialog(null)} />}
      {dialog === 'cancel' && <ReasonDialog title={`Cancel ${count.number}`} fieldLabel="Reason for cancelling" required confirm="Cancel count" variant="danger" busy={cancel.isPending}
        intro="No differences are posted for a cancelled count; the freeze is released." onConfirm={(t) => cancel.mutate(t)} onClose={() => setDialog(null)} />}
      {dialog === 'recount' && <RecountDialog busy={recount.isPending} onConfirm={(args) => recount.mutate(args)} onClose={() => setDialog(null)} />}
    </>
  );
}

function RecountDialog({ busy, onConfirm, onClose }: { busy: boolean; onConfirm: (args: { reason: string; materials: string[] }) => void; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const [materials, setMaterials] = useState('');
  const named = materials.split(/[\s,;]+/).map((m) => m.trim()).filter(Boolean);
  return (
    <Dialog open title="Request a recount" onClose={onClose}>
      <div className="space-y-3">
        <Field label="Materials to recount" hint="Empty: every line outside the tolerance">
          {(id, by) => <Textarea id={id} aria-describedby={by} value={materials} onChange={(e) => setMaterials(e.target.value)} className="font-mono text-xs" />}
        </Field>
        <Field label="Reason" required hint="At least 3 characters; shown to the counters">{(id, by) => <Input id={id} aria-describedby={by} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Back</Button>
        <Button variant="primary" disabled={reason.trim().length < 3} busy={busy} onClick={() => onConfirm({ reason: reason.trim(), materials: named })}>Request recount</Button>
      </div>
    </Dialog>
  );
}

