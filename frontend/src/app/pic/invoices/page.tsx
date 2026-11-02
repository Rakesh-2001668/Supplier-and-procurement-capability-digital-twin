'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Empty, Field, Input, LinkButton, Loading, PageHeader, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, inr, qty } from '@/lib/pic/format';
import { useApi, useCommand, useList } from '@/lib/pic/hooks';
import { BlockChip, CaptureInvoiceDialog, hasRole, InvoiceRow, MatchChip, today, useSessionUser } from './_components';
import { ConsignmentSettlementDialog, PaymentFilesCard, SETTLE_ROLES } from './_ops';

type Filters = { status: string; supplier: string; q: string; company_code: string; date_from: string; date_to: string; payment_status: string;
  payment_block: string; has_open_exceptions: string; msme: string; match_type: string };
const NO_FILTERS: Filters = { status: '', supplier: '', q: '', company_code: '', date_from: '', date_to: '', payment_status: '', payment_block: '',
  has_open_exceptions: '', msme: '', match_type: '' };
const YES_NO = [{ value: '', label: 'Any' }, { value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }];
const PAYMENT_STATUSES = ['', 'UNPAID', 'IN_PAYMENT', 'PAID'];
const MATCH_TYPES = ['', '2WAY', '3WAY', '4WAY', 'SES', 'ERS'];

function queryOf(filters: Filters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value.trim()) params.set(key, value.trim());
  const text = params.toString();
  return text ? `?${text}` : '';
}

const STATUSES = ['', 'CAPTURED', 'DUPLICATE_CHECK', 'MATCHING', 'EXCEPTION', 'MATCHED', 'APPROVED', 'POSTED', 'PAID', 'REJECTED'];

type Grir = { po: string; line: number; qty: string; accrualMinor: number };
type RunResult = { run: string; replayed?: boolean; paid: { invoice: string; payment: string; amountMinor: number; clearing: string | null; tdsMinor?: number;
  discountMinor?: number; msme?: boolean; dueDate?: string; currency?: string }[]; skipped: { invoice: string; reason: string }[] };
type Proposal = { runDate: string; totalMinor: number; skipped: { invoice: string; supplier?: string; reason: string }[];
  bySupplier: { supplier: string; invoices: number; amountMinor: number; currency: string }[];
  items: { invoice: string; supplier: string; supplierName: string; dueDate: string; overdueDays: number; msme: boolean; msmeCapped: boolean; grossMinor: number;
    creditNotesMinor: number; debitNotesMinor: number; retentionMinor: number; discountMinor: number; tdsMinor: number; amountMinor: number; currency: string }[] };

export default function Invoices() {
  const router = useRouter();
  const user = useSessionUser();
  const [draft, setDraft] = useState<Filters>(NO_FILTERS);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [dialog, setDialog] = useState<'capture' | 'run' | 'settle' | null>(null);
  const list = useList<InvoiceRow>(`/invoices${queryOf(filters)}`);
  const set = (key: keyof Filters) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [key]: e.target.value }));
  const active = Object.values(filters).filter((v) => v.trim()).length;
  const canCapture = hasRole(user, 'AP_CLERK');
  const canRun = hasRole(user, 'FINANCE_CONTROLLER');

  return (
    <div className="space-y-5">
      <PageHeader kpis="M10" eyebrow="INV-01 · Invoice worklist" title="Invoices"
        subtitle="Captured invoices are duplicate-checked, matched 2-way, 3-way (against received quantity), 4-way for quality-managed lines (against inspection-accepted quantity) or against approved service entries, then approved, posted to ERP exactly once and paid."
        actions={<>
          {canCapture && <Button variant="primary" onClick={() => setDialog('capture')}>Capture invoice</Button>}
          {canRun && <Button onClick={() => setDialog('run')}>Payment run</Button>}
          {hasRole(user, ...SETTLE_ROLES) && <Button onClick={() => setDialog('settle')}>Consignment settlement</Button>}
          <LinkButton href="/pic/invoices/reconciliation">Posting & reconciliation</LinkButton>
          <LinkButton href="/pic/invoices/insights">Payables insights</LinkButton>
        </>} />

      <Card title={`Worklist${active ? ` · ${active} filter${active > 1 ? 's' : ''}` : ''}`}>
        <form className="mb-4 grid gap-3 md:grid-cols-4" onSubmit={(e) => { e.preventDefault(); setFilters(draft); }} aria-label="Invoice filters">
          <Field label="Search">{(id) => <Input id={id} placeholder="Invoice, supplier invoice or ERP no." value={draft.q} onChange={set('q')} />}</Field>
          <Field label="Status">{(id) => <Select id={id} value={draft.status} onChange={set('status')}
            options={STATUSES.map((s) => ({ value: s, label: s ? s.replace(/_/g, ' ').toLowerCase() : 'All statuses' }))} />}</Field>
          <Field label="Supplier code(s)">{(id) => <Input id={id} placeholder="e.g. TF001, KD002" value={draft.supplier} onChange={set('supplier')} />}</Field>
          <Field label="Company code">{(id) => <Input id={id} placeholder="1000" value={draft.company_code} onChange={set('company_code')} />}</Field>
          <Field label="Invoice date from">{(id) => <Input id={id} type="date" value={draft.date_from} onChange={set('date_from')} />}</Field>
          <Field label="Invoice date to">{(id) => <Input id={id} type="date" value={draft.date_to} onChange={set('date_to')} />}</Field>
          <Field label="Payment">{(id) => <Select id={id} value={draft.payment_status} onChange={set('payment_status')}
            options={PAYMENT_STATUSES.map((s) => ({ value: s, label: s ? s.replace(/_/g, ' ').toLowerCase() : 'Any payment status' }))} />}</Field>
          <Field label="Match">{(id) => <Select id={id} value={draft.match_type} onChange={set('match_type')}
            options={MATCH_TYPES.map((s) => ({ value: s, label: s || 'Any match type' }))} />}</Field>
          <Field label="Payment block">{(id) => <Select id={id} value={draft.payment_block} onChange={set('payment_block')} options={YES_NO} />}</Field>
          <Field label="Open exceptions">{(id) => <Select id={id} value={draft.has_open_exceptions} onChange={set('has_open_exceptions')} options={YES_NO} />}</Field>
          <Field label="MSME supplier">{(id) => <Select id={id} value={draft.msme} onChange={set('msme')} options={YES_NO} />}</Field>
          <div className="flex items-end gap-2">
            <Button type="submit" variant="primary">Apply</Button>
            <Button type="button" onClick={() => { setDraft(NO_FILTERS); setFilters(NO_FILTERS); }}>Reset</Button>
          </div>
        </form>
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

      {hasRole(user, 'AP_CLERK', 'FINANCE_CONTROLLER') && <PaymentFilesCard canManage={canRun} />}

      {dialog === 'capture' && <CaptureInvoiceDialog onClose={() => setDialog(null)} onCaptured={(inv) => router.push(`/pic/invoices/${inv.id}`)} />}
      {dialog === 'run' && <PaymentRunDialog onClose={() => setDialog(null)} />}
      {dialog === 'settle' && <ConsignmentSettlementDialog onClose={() => setDialog(null)} />}
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

const codes = (text: string) => text.split(/[\s,;]+/).map((c) => c.trim()).filter(Boolean);

function PaymentRunDialog({ onClose }: { onClose: () => void }) {
  const [runDate, setRunDate] = useState(today());
  const [includeNotDue, setIncludeNotDue] = useState(false);
  const [suppliers, setSuppliers] = useState('');
  const [invoices, setInvoices] = useState('');
  const [result, setResult] = useState<RunResult | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const selection = () => ({ supplier_codes: codes(suppliers).length ? codes(suppliers) : undefined, invoice_numbers: codes(invoices).length ? codes(invoices) : undefined });
  const preview = useCommand(() => {
    const params = new URLSearchParams({ run_date: runDate, include_not_due: String(includeNotDue) });
    codes(suppliers).forEach((c) => params.append('supplier', c));
    codes(invoices).forEach((c) => params.append('invoice', c));
    return api.get<Proposal>(`/payments/proposal?${params.toString()}`);
  }, { onSuccess: setProposal });
  const run = useCommand(() => api.post<RunResult>('/payments/runs', { run_date: runDate, include_not_due: includeNotDue, ...selection() }), {
    success: (r) => `${r.run}: ${r.paid.length} paid, ${r.skipped.length} skipped`, onSuccess: setResult,
  });
  const changed = () => setProposal(null);
  return (
    <Dialog open title="Payment run" onClose={onClose}>
      {!result ? (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Run date (value date)">
              {(id) => <Input id={id} type="date" required value={runDate} onChange={(e) => { setRunDate(e.target.value); changed(); }} />}
            </Field>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="h-4 w-4" checked={includeNotDue} onChange={(e) => { setIncludeNotDue(e.target.checked); changed(); }} />
                Include invoices not yet due
              </label>
            </div>
            <Field label="Suppliers (optional)" hint="Supplier codes separated by commas; empty pays every supplier.">
              {(id) => <Input id={id} placeholder="e.g. TF001, KD002" value={suppliers} onChange={(e) => { setSuppliers(e.target.value); changed(); }} />}
            </Field>
            <Field label="Invoices (optional)" hint="Invoice numbers separated by commas; empty pays every due invoice.">
              {(id) => <Input id={id} placeholder="e.g. INV-TF-8812" value={invoices} onChange={(e) => { setInvoices(e.target.value); changed(); }} />}
            </Field>
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Pays posted, unblocked, unpaid invoices due by the run date, net of credit notes, debit notes, retention, early-payment discount and TDS.
            Micro and small suppliers fall due 45 days after acceptance. Invoices are skipped when the supplier is blocked, has no verified bank account,
            a bank change is still in its cooling-off period, the posting period is closed, or segregation of duties forbids you releasing the payment
            (you cannot pay an invoice you approved).
          </p>
          {preview.error && <ProblemBox error={preview.error} />}
          {proposal && <ProposalView proposal={proposal} />}
          <div className="mt-4 flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button disabled={!runDate} busy={preview.isPending} onClick={() => preview.mutate()}>Preview proposal</Button>
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
                    <span>{p.invoice} → <span className="font-mono">{p.payment}</span>{p.clearing ? ` · ERP clearing ${p.clearing}` : ''}
                      {p.msme ? ' · MSME' : ''}{p.tdsMinor ? ` · TDS ${inr(p.tdsMinor)}` : ''}{p.discountMinor ? ` · discount ${inr(p.discountMinor)}` : ''}</span>
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
                {result.skipped.map((s, i) => <li key={`${s.invoice}-${i}`} className="py-1.5"><span className="font-medium">{s.invoice}</span> — {s.reason}</li>)}
              </ul>
            ) : <p className="mt-1 text-sm text-slate-600">No invoices were skipped.</p>}
          </div>
          <p className="text-xs text-slate-500">Generate the bank file for {result.run} under “Bank payment files”.</p>
          <div className="flex justify-end"><Button variant="primary" onClick={onClose}>Done</Button></div>
        </div>
      )}
    </Dialog>
  );
}

function ProposalView({ proposal }: { proposal: Proposal }) {
  return (
    <div className="mt-4 space-y-3" aria-label="Payment proposal">
      <p className="text-sm font-medium">Proposal for {date(proposal.runDate)} · {proposal.items.length} to pay · {inr(proposal.totalMinor)} (INR) · {proposal.skipped.length} skipped</p>
      {proposal.items.length > 0 && (
        <div className="max-h-64 overflow-auto rounded-lg border border-slate-200">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-50 text-left uppercase tracking-wide text-slate-500">
              <tr><th className="px-2 py-1.5">Invoice</th><th className="px-2 py-1.5">Supplier</th><th className="px-2 py-1.5">Due</th><th className="px-2 py-1.5 text-right">Discount</th>
                <th className="px-2 py-1.5 text-right">TDS</th><th className="px-2 py-1.5 text-right">Pay</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {proposal.items.map((i) => (
                <tr key={i.invoice}>
                  <td className="px-2 py-1.5 font-medium">{i.invoice}</td>
                  <td className="px-2 py-1.5">{i.supplier}{i.msme ? <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] font-semibold text-amber-800">MSME</span> : null}</td>
                  <td className="px-2 py-1.5">{date(i.dueDate)}{i.overdueDays > 0 ? <span className="ml-1 text-red-700">{i.overdueDays}d late</span> : null}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{i.discountMinor ? inr(i.discountMinor) : '–'}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{i.tdsMinor ? inr(i.tdsMinor) : '–'}</td>
                  <td className="px-2 py-1.5 text-right font-semibold tabular-nums">{i.currency === 'INR' ? inr(i.amountMinor) : `${i.currency} ${(i.amountMinor / 100).toFixed(2)}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {proposal.skipped.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-lg border border-amber-200 bg-amber-50 text-xs text-amber-900">
          {proposal.skipped.map((s, i) => <li key={`${s.invoice}-${i}`} className="px-2 py-1.5"><span className="font-medium">{s.invoice}</span> — {s.reason}</li>)}
        </ul>
      )}
    </div>
  );
}
