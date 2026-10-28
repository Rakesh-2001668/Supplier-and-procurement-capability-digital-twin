'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Empty, Field, Input, LinkButton, Loading, PageHeader, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, inr, qty } from '@/lib/pic/format';
import { useApi, useCommand, useList } from '@/lib/pic/hooks';
import { BlockChip, CaptureInvoiceDialog, hasRole, InvoiceRow, MatchChip, today, useSessionUser } from './_components';

const STATUSES = ['', 'CAPTURED', 'DUPLICATE_CHECK', 'MATCHING', 'EXCEPTION', 'MATCHED', 'APPROVED', 'POSTED', 'PAID', 'REJECTED'];

type Grir = { po: string; line: number; qty: string; accrualMinor: number };
type RunResult = { run: string; replayed?: boolean; paid: { invoice: string; payment: string; amountMinor: number; clearing: string | null }[];
  skipped: { invoice: string; reason: string }[] };

export default function Invoices() {
  const router = useRouter();
  const user = useSessionUser();
  const [status, setStatus] = useState('');
  const [dialog, setDialog] = useState<'capture' | 'run' | null>(null);
  const list = useList<InvoiceRow>(`/invoices${status ? `?status=${status}` : ''}`);
  const canCapture = hasRole(user, 'AP_CLERK');
  const canRun = hasRole(user, 'FINANCE_CONTROLLER');

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="INV-01 · Invoice worklist" title="Invoices"
        subtitle="Captured invoices are duplicate-checked, matched 2-way, 3-way (against accepted quantity) or against approved service entries, then approved, posted to ERP exactly once and paid."
        actions={<>
          {canCapture && <Button variant="primary" onClick={() => setDialog('capture')}>Capture invoice</Button>}
          {canRun && <Button onClick={() => setDialog('run')}>Payment run</Button>}
          <LinkButton href="/pic/invoices/reconciliation">Posting & reconciliation</LinkButton>
          <LinkButton href="/pic/invoices/insights">Payables insights</LinkButton>
        </>} />

      <Card title="Worklist" actions={
        <Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}
          options={STATUSES.map((s) => ({ value: s, label: s ? s.replace(/_/g, ' ').toLowerCase() : 'All statuses' }))} />
      }>
        <DataTable<InvoiceRow>
          rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
          loadingMore={list.isFetchingNextPage} rowHref={(r) => `/pic/invoices/${r.id}`} empty="No invoices"
          columns={[
            { key: 'number', header: 'Invoice' },
            { key: 'supplier_code', header: 'Supplier' },
            { key: 'invoice_date', header: 'Date', render: (r) => date(r.invoice_date) },
            { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
            { key: 'gross_minor', header: 'Gross', align: 'right', render: (r) => inr(r.gross_minor) },
            { key: 'match_type', header: 'Match', render: (r) => <MatchChip inv={r} /> },
            { key: 'open_exceptions', header: 'Open exc.', align: 'right', render: (r) => r.open_exceptions
              ? <span className="font-semibold text-amber-700">{r.open_exceptions}</span> : '0' },
            { key: 'payment_block', header: 'Payment block', render: (r) => <BlockChip blocked={r.payment_block} /> },
            { key: 'due_date', header: 'Due', render: (r) => date(r.due_date) },
            { key: 'erp_doc_no', header: 'ERP doc', render: (r) => r.erp_doc_no ?? '–' },
            { key: 'payment_status', header: 'Payment', render: (r) => r.payment_status ? <StatusChip status={r.payment_status} /> : '–' },
          ]}
        />
      </Card>

      <GrirCard />

      {dialog === 'capture' && <CaptureInvoiceDialog onClose={() => setDialog(null)} onCaptured={(inv) => router.push(`/pic/invoices/${inv.id}`)} />}
      {dialog === 'run' && <PaymentRunDialog onClose={() => setDialog(null)} />}
    </div>
  );
}

function GrirCard() {
  const { data, isLoading, error } = useApi<Grir[]>('/grir');
  const total = (data ?? []).reduce((s, r) => s + r.accrualMinor, 0);
  return (
    <Card title="GR/IR accruals · received, not yet invoiced" actions={data && data.length > 0 ? <span className="text-sm font-semibold tabular-nums">{inr(total)}</span> : undefined}>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : !data?.length ? (
        <Empty title="No open GR/IR balance" hint="Every accepted quantity has been invoiced." />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr><th className="px-3 py-2">PO</th><th className="px-3 py-2">Line</th><th className="px-3 py-2 text-right">Accepted, not invoiced</th><th className="px-3 py-2 text-right">Accrual</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((r) => (
                <tr key={`${r.po}-${r.line}`}>
                  <td className="px-3 py-2"><Link href={`/pic/purchase-orders/${encodeURIComponent(r.po)}`} className="font-medium text-[#1A56DB] hover:underline">{r.po}</Link></td>
                  <td className="px-3 py-2">{r.line}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{qty(r.qty)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{inr(r.accrualMinor)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function PaymentRunDialog({ onClose }: { onClose: () => void }) {
  const [runDate, setRunDate] = useState(today());
  const [includeNotDue, setIncludeNotDue] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const run = useCommand(() => api.post<RunResult>('/payments/runs', { run_date: runDate, include_not_due: includeNotDue }), {
    success: (r) => `${r.run}: ${r.paid.length} paid, ${r.skipped.length} skipped`, onSuccess: setResult,
  });
  return (
    <Dialog open title="Payment run" onClose={onClose}>
      {!result ? (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Run date (value date)">
              {(id) => <Input id={id} type="date" required value={runDate} onChange={(e) => setRunDate(e.target.value)} />}
            </Field>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="h-4 w-4" checked={includeNotDue} onChange={(e) => setIncludeNotDue(e.target.checked)} />
                Include invoices not yet due
              </label>
            </div>
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Pays posted, unblocked, unpaid invoices due by the run date, net of credit notes. Invoices are skipped when the supplier has no verified
            bank account, a bank change is still in its cooling-off period, or segregation of duties forbids you approving the payment.
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={!runDate} busy={run.isPending} onClick={() => run.mutate()}>Execute run</Button>
          </div>
        </>
      ) : (
        <div className="space-y-4">
          <p className="text-sm">Run <span className="font-mono font-semibold">{result.run}</span>{result.replayed ? ' (replayed)' : ''} · {result.paid.length} paid · {result.skipped.length} skipped</p>
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Paid</h3>
            {result.paid.length ? (
              <ul className="mt-1 divide-y divide-slate-100 text-sm">
                {result.paid.map((p) => (
                  <li key={p.payment} className="flex flex-wrap justify-between gap-2 py-1.5">
                    <span>{p.invoice} → <span className="font-mono">{p.payment}</span>{p.clearing ? ` · ERP clearing ${p.clearing}` : ''}</span>
                    <span className="font-semibold tabular-nums">{inr(p.amountMinor)}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="mt-1 text-sm text-slate-600">Nothing was due for payment.</p>}
          </div>
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Skipped</h3>
            {result.skipped.length ? (
              <ul className="mt-1 divide-y divide-slate-100 text-sm">
                {result.skipped.map((s) => <li key={s.invoice} className="py-1.5"><span className="font-medium">{s.invoice}</span> — {s.reason}</li>)}
              </ul>
            ) : <p className="mt-1 text-sm text-slate-600">No invoices were skipped.</p>}
          </div>
          <div className="flex justify-end"><Button variant="primary" onClick={onClose}>Done</Button></div>
        </div>
      )}
    </Dialog>
  );
}
