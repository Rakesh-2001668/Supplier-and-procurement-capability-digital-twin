'use client';

import { useState } from 'react';
import { Button, DataTable, Dialog, Empty, Facts, Input, Loading, ProblemBox, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, inr } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type RetentionInvoice = { invoice: string; invoiceId: string; status: string; erpDocument: string | null; withheldMinor: number; pendingMinor: number;
  releasedMinor: number; outstandingMinor: number };
type RetentionRelease = { number: string; amountMinor: number; releaseDate: string; status: string; paymentStatus: string; reference: string | null };
type RetentionPosition = { po: string; retentionPct: string | null; withheldMinor: number; pendingMinor: number; releasedMinor: number;
  outstandingMinor: number; invoices: RetentionInvoice[]; releases: RetentionRelease[] };

/** Retention withheld on a construction / subcontract order: per invoice, released so far, outstanding; AP or finance releases it. */
export function RetentionTab({ poNumber, canRelease }: { poNumber: string; canRelease: boolean }) {
  const { data, isLoading, error } = useApi<RetentionPosition>(`/purchase-orders/${encodeURIComponent(poNumber)}/retention`);
  const [open, setOpen] = useState(false);
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data) return null;
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        {Number(data.retentionPct ?? 0)}% of the taxable value of every invoice is withheld from payment (GST is charged on the full value) and
        paid when it is released, e.g. on the completion certificate.
      </p>
      <Facts items={[
        ['Withheld (posted invoices)', inr(data.withheldMinor)], ['Pending (invoices in matching)', inr(data.pendingMinor)],
        ['Released', inr(data.releasedMinor)], ['Outstanding', <span key="o" className="font-semibold">{inr(data.outstandingMinor)}</span>],
      ]} />
      {canRelease && data.outstandingMinor > 0 && (
        <div><Button variant="primary" onClick={() => setOpen(true)}>Release retention</Button></div>
      )}
      {!data.invoices.length ? <Empty title="No invoices yet" hint="Retention is withheld when an invoice against this order is posted." /> : (
        <DataTable<RetentionInvoice> rows={data.invoices.map((i) => ({ ...i, id: i.invoiceId }))}
          rowHref={(i) => `/pic/invoices/${encodeURIComponent(i.invoice)}`} columns={[
            { key: 'invoice', header: 'Invoice' },
            { key: 'status', header: 'Status', render: (i) => <StatusChip status={i.status} /> },
            { key: 'erpDocument', header: 'ERP document', render: (i) => i.erpDocument ?? '–' },
            { key: 'withheldMinor', header: 'Withheld', align: 'right', render: (i) => inr(i.withheldMinor || i.pendingMinor) },
            { key: 'releasedMinor', header: 'Released', align: 'right', render: (i) => inr(i.releasedMinor) },
            { key: 'outstandingMinor', header: 'Outstanding', align: 'right', render: (i) => inr(i.outstandingMinor) },
          ]} />
      )}
      {data.releases.length > 0 && (
        <DataTable<RetentionRelease> rows={data.releases.map((r) => ({ ...r, id: r.number }))}
          rowHref={(r) => `/pic/invoices/${encodeURIComponent(r.number)}`} columns={[
            { key: 'number', header: 'Release' },
            { key: 'releaseDate', header: 'Date', render: (r) => date(r.releaseDate) },
            { key: 'amountMinor', header: 'Amount', align: 'right', render: (r) => inr(r.amountMinor) },
            { key: 'reference', header: 'Reference', render: (r) => r.reference ?? '–' },
            { key: 'paymentStatus', header: 'Payment', render: (r) => <StatusChip status={r.paymentStatus} /> },
          ]} />
      )}
      {open && <ReleaseDialog poNumber={poNumber} outstandingMinor={data.outstandingMinor} onClose={() => setOpen(false)} />}
    </div>
  );
}

function ReleaseDialog({ poNumber, outstandingMinor, onClose }: { poNumber: string; outstandingMinor: number; onClose: () => void }) {
  const [reference, setReference] = useState('');
  const [reason, setReason] = useState('');
  const [amount, setAmount] = useState('');
  const amountMinor = amount ? Math.round(Number(amount) * 100) : undefined;
  const invalid = amountMinor !== undefined && (!Number.isFinite(amountMinor) || amountMinor <= 0 || amountMinor > outstandingMinor);
  const release = useCommand(() => api.post<{ number: string }>(`/purchase-orders/${encodeURIComponent(poNumber)}/retention-release`,
    { reference, reason, ...(amountMinor ? { amountMinor } : {}) }),
  { success: (r) => `${r.number} created; the next payment run pays it`, onSuccess: onClose });
  return (
    <Dialog open title={`Release retention on ${poNumber}`} onClose={onClose}>
      <div className="grid gap-3">
        <label className="flex flex-col gap-1 text-xs font-medium">Reference (completion certificate, bank guarantee)
          <Input value={reference} onChange={(e) => setReference(e.target.value)} /></label>
        <label className="flex flex-col gap-1 text-xs font-medium">Amount in ₹ (empty = all outstanding {inr(outstandingMinor)})
          <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
        <label className="flex flex-col gap-1 text-xs font-medium">Reason<Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={reference.length < 3 || reason.length < 3 || invalid} busy={release.isPending}
          onClick={() => release.mutate()}>Release</Button>
      </div>
    </Dialog>
  );
}
