'use client';

import { useParams } from 'next/navigation';
import { useState } from 'react';
import { ObjectPage } from '@/components/pic/object';
import { Button, Card, DataTable, Dialog, Empty, Facts, Field, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, inr, label, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { BlockChip, hasRole, MatchChip, useSessionUser } from '../_components';

type MatchDetail = { invoicedQty?: string; creditedQty?: string; netQty?: string; poQty?: string; receivedQty?: string; acceptedQty?: string;
  alreadyInvoicedQty?: string; sesApprovedMinor?: number; poPriceMinor?: number; invoicePriceMinor?: number };
type InvLine = { id: string; line_no: number; description: string; qty: string; unit_price_minor: number; net_minor: number; hsn_code: string | null;
  gst_rate: string; tax_minor: number; match_status: string | null; match_detail: MatchDetail | null };
type InvException = { id: string; invoice_line_id: string | null; type: string; delta: Record<string, string | number>; detail: string;
  suggested_action: string; status: string; resolution: string | null; resolution_note: string | null; ai_ref: string | null; created_at: string };
type CreditNote = { id: string; number: string; supplier_credit_note_no: string; note_date: string; reason: string; net_minor: number; tax_minor: number;
  gross_minor: number; lines: { invoice_line: number; qty: string }[] };
type Payment = { id: string; number: string; amount_minor: number; value_date: string; status: string; run_ref: string | null };
type Invoice = { id: string; number: string; supplier_invoice_no: string; fiscal_year: string; company_code: string; invoice_date: string; channel: string;
  irn: string | null; irn_valid: boolean | null; net_minor: number; tax_minor: number; gross_minor: number; status: string; match_type: string | null;
  first_pass_matched: boolean | null; payment_block: boolean | null; due_date: string | null; erp_doc_no: string | null; posting_key: string | null;
  posted_at: string | null; payment_status: string | null; rule_set_version: string | null; duplicate_of: string | null;
  supplier: { id: string; code: string; name: string }; lines: InvLine[]; exceptions: InvException[]; creditNotes: CreditNote[]; payments: Payment[] };
type PostResult = { status: string; erpDocument?: string | null; replayed?: boolean; integrationStatus?: string; attempts?: number; error?: string | null };

const RESOLUTIONS = [
  { value: 'CREDIT_NOTE_RECEIVED', label: 'Credit note received' },
  { value: 'PRICE_ACCEPTED', label: 'Price variance accepted' },
  { value: 'GR_POSTED', label: 'Goods receipt now posted' },
  { value: 'NOT_DUPLICATE', label: 'Not a duplicate' },
  { value: 'DISPUTE', label: 'Dispute with supplier' },
];
const DEFAULT_RESOLUTION: Record<string, string> = { QUANTITY: 'CREDIT_NOTE_RECEIVED', PRICE: 'PRICE_ACCEPTED', MISSING_GR: 'GR_POSTED', DUPLICATE: 'NOT_DUPLICATE' };

function irnText(inv: Invoice) {
  if (!inv.irn) return inv.channel === 'E_INVOICE' ? 'missing' : 'not applicable';
  return inv.irn_valid === true ? 'valid' : inv.irn_valid === false ? 'INVALID' : 'not checked';
}

function deltaText(delta: Record<string, string | number>) {
  if (!delta || !Object.keys(delta).length) return '–';
  return Object.entries(delta).map(([k, v]) => k.endsWith('Minor') ? `${k.replace(/Minor$/, '')} ${inr(Number(v))}` : `${k} ${v}`).join(', ');
}

export default function InvoicePage() {
  const { id } = useParams<{ id: string }>();
  const ref = encodeURIComponent(decodeURIComponent(id));
  const user = useSessionUser();
  const { data: inv, isLoading, error } = useApi<Invoice>(`/invoices/${ref}`);
  const [resolving, setResolving] = useState<InvException | null>(null);
  const [posted, setPosted] = useState<(PostResult & { key: string }) | null>(null);

  const ap = hasRole(user, 'AP_CLERK');
  const approver = hasRole(user, 'AP_CLERK', 'FINANCE_CONTROLLER');
  const postingKey = inv && user ? `${user.tenant}|${inv.company_code}|${inv.supplier.code}|${inv.supplier_invoice_no}` : '';

  const rematch = useCommand(() => api.post<{ status: string; exceptions: unknown[] }>(`/invoices/${inv!.id}/match`), {
    success: (r) => `Matched again · ${r.status.toLowerCase()}${r.exceptions.length ? ` · ${r.exceptions.length} exception(s)` : ''}`,
  });
  const approve = useCommand(() => api.post(`/invoices/${inv!.id}/approve`), { success: 'Invoice approved for posting' });
  const post = useCommand(() => api.post<PostResult>(`/invoices/${inv!.id}/post`, {}, { idempotencyKey: postingKey }), {
    success: (r) => r.erpDocument ? `ERP document ${r.erpDocument}${r.replayed ? ' (replayed)' : ''}` : `Posting ${r.status.toLowerCase()}`,
    onSuccess: (r) => setPosted({ ...r, key: postingKey }),
  });

  const lineNo = (lineId: string | null) => inv?.lines.find((l) => l.id === lineId)?.line_no;
  const openExceptions = inv?.exceptions.filter((e) => e.status === 'OPEN') ?? [];

  return (
    <>
      <ObjectPage
        type="INVOICE" docRef={inv?.number ?? ''} eyebrow="INV-04 · Invoice" loading={isLoading} error={error}
        title={<>{inv?.number} <span className="text-base font-normal text-slate-500">{inv?.supplier.name}</span></>}
        status={inv?.status}
        actions={inv && (
          <>
            {ap && ['EXCEPTION', 'DUPLICATE_CHECK'].includes(inv.status) && (
              <Button busy={rematch.isPending} onClick={() => rematch.mutate()}>Re-run match</Button>
            )}
            {approver && inv.status === 'MATCHED' && <Button variant="primary" busy={approve.isPending} onClick={() => approve.mutate()}>Approve</Button>}
            {ap && inv.status === 'APPROVED' && <Button variant="primary" busy={post.isPending} disabled={!postingKey} onClick={() => post.mutate()}>Post to ERP</Button>}
            {ap && ['POSTED', 'PAID'].includes(inv.status) && (
              <Button busy={post.isPending} disabled={!postingKey} onClick={() => post.mutate()}>Retry post (idempotent)</Button>
            )}
          </>
        )}
        facts={inv && (
          <div className="space-y-4">
            {posted && (
              <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
                <p className="font-semibold">
                  {posted.erpDocument ? <>ERP document {posted.erpDocument}</> : <>Posting {label(posted.status)}</>}
                  {' · '}status {label(posted.status)} · {posted.replayed ? 'replayed (no second posting)' : 'first posting'}
                </p>
                {posted.integrationStatus && <p>Integration {label(posted.integrationStatus)} after {posted.attempts} attempt(s){posted.error ? ` — ${posted.error}` : ''}</p>}
                <p className="mt-1 text-xs">
                  Posted with Idempotency-Key <span className="font-mono">{posted.key}</span>. Retrying with the same key returns this same ERP
                  document instead of posting the invoice twice.
                </p>
              </div>
            )}
            <Facts items={[
              ['Supplier', `${inv.supplier.code} · ${inv.supplier.name}`], ['Supplier invoice no.', inv.supplier_invoice_no],
              ['Invoice date', date(inv.invoice_date)], ['Channel', label(inv.channel)],
              ['IRN', <span key="irn" className={inv.irn_valid === false ? 'text-red-700' : ''}>{irnText(inv)}</span>],
              ['Net', inr(inv.net_minor)], ['Tax (GST)', inr(inv.tax_minor)], ['Gross', inr(inv.gross_minor)],
              ['Match type', <MatchChip key="m" inv={inv} />],
              ['First-pass match', inv.first_pass_matched === null ? 'not matched yet' : inv.first_pass_matched ? 'yes' : 'no'],
              ['Payment block', <BlockChip key="b" blocked={inv.payment_block} />], ['Due date', date(inv.due_date)],
              ['ERP document', inv.erp_doc_no ?? 'not posted yet'], ['Payment status', inv.payment_status ? <StatusChip key="p" status={inv.payment_status} /> : '–'],
              ['Company code / FY', `${inv.company_code} · ${inv.fiscal_year}`], ['Rules', inv.rule_set_version ?? '–'],
            ]} />
            {inv.irn && <p className="break-all font-mono text-[11px] text-slate-500">IRN {inv.irn}</p>}
            {inv.duplicate_of && <p className="text-sm text-amber-800">Suspected duplicate of {inv.duplicate_of}</p>}
            {inv.status === 'APPROVED' && ap && (
              <p className="text-xs text-slate-500">Posting key: <span className="font-mono">{postingKey}</span> — tenant | company code | supplier | invoice number.</p>
            )}
          </div>
        )}
        lines={inv && (
          <DataTable<InvLine> rows={inv.lines} columns={[
            { key: 'line_no', header: 'Line' },
            { key: 'description', header: 'Item', render: (l) => <><p>{l.description}</p><p className="text-xs text-slate-500">HSN {l.hsn_code ?? '–'} · GST {l.gst_rate}%</p></> },
            { key: 'invoiced', header: 'Invoiced', align: 'right', render: (l) => qty(l.match_detail?.invoicedQty ?? l.qty) },
            { key: 'credited', header: 'Credited', align: 'right', render: (l) => qty(l.match_detail?.creditedQty) },
            { key: 'net', header: 'Net qty', align: 'right', render: (l) => qty(l.match_detail?.netQty) },
            { key: 'accepted', header: 'Accepted', align: 'right', render: (l) => l.match_detail?.sesApprovedMinor !== undefined
              ? <span title="Approved service entries">{inr(l.match_detail.sesApprovedMinor)} SES</span> : qty(l.match_detail?.acceptedQty) },
            { key: 'already', header: 'Already invoiced', align: 'right', render: (l) => qty(l.match_detail?.alreadyInvoicedQty) },
            { key: 'price', header: 'PO vs invoice price', align: 'right', render: (l) => {
              const po = l.match_detail?.poPriceMinor; const iv = l.match_detail?.invoicePriceMinor ?? l.unit_price_minor;
              return <span className={po !== undefined && po !== iv ? 'font-semibold text-amber-700' : ''}>{po !== undefined ? inr(po) : '–'} / {inr(iv)}</span>;
            } },
            { key: 'net_minor', header: 'Net value', align: 'right', render: (l) => inr(l.net_minor) },
            { key: 'match_status', header: 'Match', render: (l) => <StatusChip status={l.match_status ?? 'PENDING'} /> },
          ]} />
        )}
        extraTabs={inv ? [
          { id: 'exceptions', label: `Exceptions (${openExceptions.length} open)`, content: (
            inv.exceptions.length ? (
              <div className="space-y-3">
                {inv.exceptions.map((e) => (
                  <div key={e.id} className={`rounded-lg border p-4 ${e.status === 'OPEN' ? 'border-amber-300 bg-amber-50/50' : 'border-slate-200'}`}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded bg-slate-900 px-2 py-0.5 font-mono text-xs text-white">{e.type}</span>
                        {lineNo(e.invoice_line_id) && <span className="text-xs text-slate-600">line {lineNo(e.invoice_line_id)}</span>}
                        <StatusChip status={e.status} />
                      </div>
                      {ap && e.status === 'OPEN' && <Button variant="primary" onClick={() => setResolving(e)}>Resolve</Button>}
                    </div>
                    <p className="mt-2 text-sm">{e.detail}</p>
                    <p className="mt-1 text-sm text-slate-700"><span className="text-xs font-semibold uppercase text-slate-500">Delta</span> {deltaText(e.delta)}</p>
                    <p className="mt-1 text-sm text-slate-700"><span className="text-xs font-semibold uppercase text-slate-500">Suggested</span> {e.suggested_action}</p>
                    {e.resolution && <p className="mt-1 text-sm text-emerald-800">Resolved: {label(e.resolution)}{e.resolution_note ? ` — ${e.resolution_note}` : ''}</p>}
                    <p className="mt-1 font-mono text-[11px] text-slate-400">{[e.ai_ref, dateTime(e.created_at)].filter(Boolean).join(' · ')}</p>
                  </div>
                ))}
              </div>
            ) : <Empty title="No exceptions" hint="All lines matched within tolerance." />
          ) },
          { id: 'credit-notes', label: `Credit notes (${inv.creditNotes.length})`, content: (
            <DataTable<CreditNote> rows={inv.creditNotes} empty="No credit notes" columns={[
              { key: 'number', header: 'Credit note' },
              { key: 'note_date', header: 'Date', render: (n) => date(n.note_date) },
              { key: 'reason', header: 'Reason' },
              { key: 'lines', header: 'Lines', render: (n) => n.lines.map((l) => `line ${l.invoice_line}: ${qty(l.qty)}`).join(', ') },
              { key: 'net_minor', header: 'Net', align: 'right', render: (n) => inr(n.net_minor) },
              { key: 'tax_minor', header: 'Tax', align: 'right', render: (n) => inr(n.tax_minor) },
              { key: 'gross_minor', header: 'Gross', align: 'right', render: (n) => inr(n.gross_minor) },
            ]} />
          ) },
          { id: 'payments', label: `Payments (${inv.payments.length})`, content: (
            <DataTable<Payment> rows={inv.payments} empty="Not paid yet" columns={[
              { key: 'number', header: 'Payment' },
              { key: 'run_ref', header: 'Run', render: (p) => p.run_ref ?? '–' },
              { key: 'value_date', header: 'Value date', render: (p) => date(p.value_date) },
              { key: 'status', header: 'Status', render: (p) => <StatusChip status={p.status} /> },
              { key: 'amount_minor', header: 'Amount (net of credit notes)', align: 'right', render: (p) => inr(p.amount_minor) },
            ]} />
          ) },
        ] : []}
      />
      {inv && resolving && <ResolveDialog inv={inv} exc={resolving} onClose={() => setResolving(null)} />}
    </>
  );
}

function ResolveDialog({ inv, exc, onClose }: { inv: Invoice; exc: InvException; onClose: () => void }) {
  const [resolution, setResolution] = useState(DEFAULT_RESOLUTION[exc.type] ?? 'DISPUTE');
  const [note, setNote] = useState('');
  const [creditNote, setCreditNote] = useState(inv.creditNotes[0]?.number ?? '');
  const needsNote = resolution === 'CREDIT_NOTE_RECEIVED';
  const resolve = useCommand(() => api.post<{ status: string; dispute?: boolean }>(`/invoices/${inv.id}/exceptions/${exc.id}/resolve`, {
    resolution, note: note.trim(), credit_note: needsNote ? creditNote : undefined,
  }), {
    success: (r) => r.dispute ? 'Dispute recorded; the payment block stays' : `Exception resolved · invoice ${r.status.toLowerCase()}`,
    onSuccess: onClose,
  });
  return (
    <Dialog open title={`Resolve ${exc.type.toLowerCase().replace(/_/g, ' ')} exception`} onClose={onClose}>
      <Card className="mb-4">
        <p className="text-sm">{exc.detail}</p>
        <p className="mt-1 text-sm text-slate-600">Suggested: {exc.suggested_action}</p>
      </Card>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Resolution">
          {(id) => <Select id={id} value={resolution} onChange={(e) => setResolution(e.target.value)} options={RESOLUTIONS} />}
        </Field>
        {needsNote && (
          <Field label="Credit note" hint={inv.creditNotes.length ? undefined : 'No credit note has been received for this invoice yet'}>
            {(id) => (
              <Select id={id} value={creditNote} onChange={(e) => setCreditNote(e.target.value)}
                options={inv.creditNotes.length
                  ? inv.creditNotes.map((n) => ({ value: n.number, label: `${n.number} · ${inr(n.gross_minor)} · ${n.lines.map((l) => `${qty(l.qty)} on line ${l.invoice_line}`).join(', ')}` }))
                  : [{ value: '', label: 'None received' }]} />
            )}
          </Field>
        )}
        <div className="md:col-span-2">
          <Field label="Note (required)">
            {(id) => <Textarea id={id} required value={note} onChange={(e) => setNote(e.target.value)} placeholder="What was agreed and with whom" />}
          </Field>
        </div>
      </div>
      <p className="mt-3 text-xs text-slate-500">When the last open exception is resolved the invoice is matched again automatically. A dispute keeps the payment block.</p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!note.trim() || (needsNote && !creditNote)} busy={resolve.isPending} onClick={() => resolve.mutate()}>Resolve</Button>
      </div>
    </Dialog>
  );
}
