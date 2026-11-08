'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, DataTable, Dialog, Facts, Field, Input, Kpi, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, inr, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

// ---------------------------------------------------------------- RCV-04 returns (GET /v1/return-deliveries)
export type Settlement = { type: 'CREDIT_NOTE' | 'GOODS_RECEIPT' | 'MANUAL' | string; ref: string; qty: string; at: string; reason?: string };
export type ReturnRow = {
  id: string; number: string; status: string; gr: string | null; po: string; poLine: number; supplier: string | null; supplierName: string | null;
  material: string | null; description: string; uom: string; plant: string; qty: string; settledQty: string; openQty: string; valueMinor: number;
  openValueMinor: number; reason: string; replacementRequired: boolean; creditNoteExpected: boolean; settlements: Settlement[];
  createdAt: string | null; closedAt: string | null; version: number;
};
type AuditRow = { action: string; actor: string; at: string; reason: string | null; after: Record<string, unknown> | null };
type ReturnDetail = ReturnRow & { audit: AuditRow[] };
type ReturnList = { items: ReturnRow[]; total: number; countsByStatus: Record<string, number>; openValueMinor: number };

const RETURN_STATUSES = ['', 'CREATED', 'REPLACEMENT_DUE', 'CREDITED', 'REPLACED', 'CLOSED'];
const OPEN = ['CREATED', 'REPLACEMENT_DUE'];
const SETTLED_BY: Record<string, string> = { CREDIT_NOTE: 'credit note', GOODS_RECEIPT: 'replacement receipt', MANUAL: 'closed by hand' };

function query(params: Record<string, string | boolean | undefined>): string {
  const parts = Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== false)
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join('&')}` : '';
}

function SettlementList({ items }: { items: Settlement[] }) {
  if (!items.length) return <span className="text-slate-500">–</span>;
  return (
    <ul className="space-y-0.5 text-xs">
      {items.map((s, i) => (
        <li key={`${s.type}-${s.ref}-${i}`}>
          <span className="font-medium">{SETTLED_BY[s.type] ?? s.type.toLowerCase()}</span>{' '}
          {s.type === 'GOODS_RECEIPT'
            ? <Link className="text-[#1A56DB] hover:underline" href={`/pic/receiving/${encodeURIComponent(s.ref)}`}>{s.ref}</Link>
            : <span className="font-mono">{s.ref}</span>}
          {' · '}{qty(s.qty)} · {dateTime(s.at)}{s.reason ? ` · ${s.reason}` : ''}
        </li>
      ))}
    </ul>
  );
}

/** Return deliveries with their settlement: awaiting a credit note (CREATED) or a replacement (REPLACEMENT_DUE), or settled (CREDITED,
 *  REPLACED) or closed by hand (CLOSED). ``gr`` limits the list to one goods receipt (the receipt's own page). */
export function ReturnsView({ gr, canReplace, canClose }: { gr?: string; canReplace: boolean; canClose: boolean }) {
  const [status, setStatus] = useState('');
  const [openOnly, setOpenOnly] = useState(!gr);
  const [supplier, setSupplier] = useState('');
  const [po, setPo] = useState('');
  const path = `/return-deliveries${query({ gr, status, open: openOnly && !status ? true : undefined, supplier: supplier.trim(), po: po.trim() })}`;
  const { data, isLoading, error } = useApi<ReturnList>(path);
  const [replacing, setReplacing] = useState<ReturnRow | null>(null);
  const [closing, setClosing] = useState<ReturnRow | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);
  const rows = data?.items ?? [];
  const counts = data?.countsByStatus ?? {};
  return (
    <div className="space-y-4">
      {!gr && (
        <p className="text-sm text-slate-600">
          Rejected goods sent back to the supplier. A return awaiting a credit note is credited when the supplier&apos;s credit note covers its quantity;
          one returned for replacement is replaced when the replacement is received. Close a return by hand only when nothing more is due.
        </p>
      )}
      <div className="grid gap-3 md:grid-cols-4">
        <Kpi label="Awaiting credit note" value={String(counts.CREATED ?? 0)} tone={(counts.CREATED ?? 0) > 0 ? 'warn' : 'default'} />
        <Kpi label="Replacement due" value={String(counts.REPLACEMENT_DUE ?? 0)} tone={(counts.REPLACEMENT_DUE ?? 0) > 0 ? 'warn' : 'default'} />
        <Kpi label="Settled" value={String((counts.CREDITED ?? 0) + (counts.REPLACED ?? 0) + (counts.CLOSED ?? 0))} tone="good" />
        <Kpi label="Open value" value={inr(data?.openValueMinor ?? 0)} hint="returned quantity not yet credited or replaced, at the PO price" />
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <Select aria-label="Filter returns by status" value={status} className="w-auto" onChange={(e) => setStatus(e.target.value)}
          options={RETURN_STATUSES.map((s) => ({ value: s, label: s ? s.replace(/_/g, ' ').toLowerCase() : 'All statuses' }))} />
        {!gr && (
          <>
            <Input aria-label="Supplier code" placeholder="Supplier code" value={supplier} onChange={(e) => setSupplier(e.target.value)} className="w-36" />
            <Input aria-label="Purchase order" placeholder="PO number" value={po} onChange={(e) => setPo(e.target.value)} className="w-36" />
          </>
        )}
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" className="h-4 w-4" checked={openOnly} disabled={!!status} onChange={(e) => setOpenOnly(e.target.checked)} />
          Open only
        </label>
      </div>
      <DataTable<ReturnRow>
        rows={rows} loading={isLoading} error={error} empty={openOnly && !status ? 'No open return deliveries' : 'No return deliveries'}
        columns={[
          { key: 'number', header: 'Return', render: (r) => (
            <button type="button" className="font-medium text-[#1A56DB] hover:underline" onClick={() => setViewing(r.number)}>{r.number}</button>
          ) },
          { key: 'gr', header: 'Receipt / PO', render: (r) => (
            <div className="text-xs">
              {r.gr ? <Link className="text-[#1A56DB] hover:underline" href={`/pic/receiving/${encodeURIComponent(r.gr)}`}>{r.gr}</Link> : '–'}
              <p className="text-slate-500">
                <Link className="hover:underline" href={`/pic/purchase-orders/${encodeURIComponent(r.po)}`}>{r.po}</Link>/{r.poLine}
              </p>
            </div>
          ) },
          { key: 'supplier', header: 'Supplier', render: (r) => <span title={r.supplierName ?? undefined}>{r.supplier ?? '–'}</span> },
          { key: 'material', header: 'Item', render: (r) => <span className="text-xs">{r.material ? `${r.material} · ` : ''}{r.description}</span> },
          { key: 'qty', header: 'Returned', align: 'right', render: (r) => qty(r.qty, r.uom) },
          { key: 'openQty', header: 'Open', align: 'right', render: (r) => Number(r.openQty)
            ? <span className="font-semibold text-amber-700">{qty(r.openQty)}</span> : qty(r.openQty) },
          { key: 'reason', header: 'Reason', render: (r) => <span className="text-xs">{r.reason}</span> },
          { key: 'follow', header: 'Settles by', render: (r) => <span className="text-xs">{r.replacementRequired ? 'replacement' : r.creditNoteExpected ? 'credit note' : '–'}</span> },
          { key: 'settlements', header: 'Settled by', render: (r) => <SettlementList items={r.settlements} /> },
          { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
          { key: 'createdAt', header: 'Created', render: (r) => date(r.createdAt) },
          { key: 'action', header: '', render: (r) => OPEN.includes(r.status) ? (
            <div className="flex flex-col gap-1">
              {canReplace && r.status === 'CREATED' && r.creditNoteExpected && <Button onClick={() => setReplacing(r)}>Request replacement</Button>}
              {canClose && <Button onClick={() => setClosing(r)}>Close</Button>}
            </div>
          ) : null },
        ]}
      />
      {replacing && <ReplacementDialog rd={replacing} onClose={() => setReplacing(null)} />}
      {closing && <CloseReturnDialog rd={closing} onClose={() => setClosing(null)} />}
      {viewing && <ReturnDetailDialog number={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}

export function ReplacementDialog({ rd, onClose }: { rd: Pick<ReturnRow, 'number' | 'qty'>; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const request = useCommand(() => api.post<{ number: string; status: string }>(`/return-deliveries/${encodeURIComponent(rd.number)}/replacement`,
    { reason: reason.trim() || undefined }), {
    success: (r) => `${r.number}: replacement requested; ${qty(rd.qty)} open again on the order`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`Request replacement · ${rd.number}`} onClose={onClose}>
      <p className="text-sm text-slate-700">
        The supplier re-delivers the returned {qty(rd.qty)} instead of issuing a credit note: the quantity is open again on the purchase order for a new
        ASN and goods receipt, and the return is replaced when that receipt is posted.
      </p>
      <div className="mt-3">
        <Field label="Note (optional, audited)">{(id) => <Textarea id={id} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={request.isPending} onClick={() => request.mutate()}>Request replacement</Button>
      </div>
    </Dialog>
  );
}

function CloseReturnDialog({ rd, onClose }: { rd: ReturnRow; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const close = useCommand(() => api.post<ReturnRow>(`/return-deliveries/${encodeURIComponent(rd.number)}/close`, { reason: reason.trim() },
    { ifMatch: `"${rd.version}"` }), { success: (r) => `${r.number} closed`, onSuccess: onClose });
  const short = reason.trim().length < 10;
  return (
    <Dialog open title={`Close return · ${rd.number}`} onClose={onClose}>
      <p className="text-sm text-slate-700">
        {qty(rd.openQty, rd.uom)} of {qty(rd.qty)} is still open ({rd.status === 'REPLACEMENT_DUE' ? 'replacement due' : 'credit note expected'}).
        Close the return only when no credit note or replacement will come, for example when the rejected quantity was never invoiced.
      </p>
      <div className="mt-3">
        <Field label="Reason (at least 10 characters, audited)">
          {(id) => <Textarea id={id} required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
      </div>
      {close.error && <div className="mt-2"><ProblemBox error={close.error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="danger" disabled={short} busy={close.isPending} onClick={() => close.mutate()}>Close return</Button>
      </div>
    </Dialog>
  );
}

/** One return delivery (GET /v1/return-deliveries/{ref}): its facts, how it was settled and its audit trail. */
function ReturnDetailDialog({ number, onClose }: { number: string; onClose: () => void }) {
  const { data, isLoading, error } = useApi<ReturnDetail>(`/return-deliveries/${encodeURIComponent(number)}`);
  return (
    <Dialog open wide title={`Return delivery · ${number}`} onClose={onClose}>
      {isLoading ? <Loading /> : error || !data ? <ProblemBox error={error} /> : (
        <div className="space-y-4">
          <div className="flex items-center gap-2"><StatusChip status={data.status} />
            {data.closedAt && <span className="text-xs text-slate-500">closed {dateTime(data.closedAt)}</span>}</div>
          <Facts items={[
            ['Goods receipt', data.gr ?? '–'], ['PO / line', `${data.po} / ${data.poLine}`],
            ['Supplier', data.supplier ? `${data.supplier} · ${data.supplierName ?? ''}` : '–'],
            ['Item', `${data.material ? `${data.material} · ` : ''}${data.description}`], ['Plant', data.plant],
            ['Returned', qty(data.qty, data.uom)], ['Settled', qty(data.settledQty)], ['Open', qty(data.openQty)],
            ['Value', inr(data.valueMinor)], ['Open value', inr(data.openValueMinor)],
            ['Settles by', data.replacementRequired ? 'replacement' : data.creditNoteExpected ? 'credit note' : '–'], ['Reason', data.reason],
          ]} />
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Settled by</p>
            <SettlementList items={data.settlements} />
          </div>
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Audit trail</p>
            <ol className="space-y-1 text-xs">
              {data.audit.map((a, i) => (
                <li key={`${a.action}-${a.at}-${i}`}><span className="font-mono">{a.action}</span> · {a.actor} · {dateTime(a.at)}{a.reason ? ` · ${a.reason}` : ''}</li>
              ))}
              {!data.audit.length && <li className="text-slate-500">No audit events</li>}
            </ol>
          </div>
        </div>
      )}
    </Dialog>
  );
}
