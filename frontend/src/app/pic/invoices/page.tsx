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

type Filters = { status: string; supplier: string; q: string; company_code: string; date_from: string; date_to: string; due_from: string; due_to: string;
  payment_status: string; payment_block: string; has_open_exceptions: string; exception_type: string; msme: string; match_type: string };
const NO_FILTERS: Filters = { status: '', supplier: '', q: '', company_code: '', date_from: '', date_to: '', due_from: '', due_to: '', payment_status: '', payment_block: '',
  has_open_exceptions: '', exception_type: '', msme: '', match_type: '' };
const EXCEPTION_TYPES = ['', 'PRICE', 'QUANTITY', 'SERVICE', 'TAX', 'DUPLICATE', 'MISSING_GR'];

/** Whole days an unpaid invoice is past its due date (0 when not due yet, paid or not posted). */
function overdueDays(due: string | null, paymentStatus: string | null, status: string) {
  if (!due || paymentStatus === 'PAID' || !['POSTED', 'APPROVED'].includes(status)) return 0;
  return Math.max(0, Math.floor((new Date(`${today()}T00:00:00Z`).getTime() - new Date(`${due}T00:00:00Z`).getTime()) / 86_400_000));
}
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
  tcsMinor?: number; tdsCertificate?: string | null; msmeInterestMinor?: number; error?: string;
  discountMinor?: number; msme?: boolean; dueDate?: string; currency?: string }[]; skipped: { invoice: string; reason: string }[] };
type Proposal = { runDate: string; totalMinor: number; skipped: { invoice: string; supplier?: string; reason: string }[];
  bySupplier: { supplier: string; invoices: number; amountMinor: number; currency: string }[];
  items: { invoice: string; supplier: string; supplierName: string; dueDate: string; overdueDays: number; msme: boolean; msmeCapped: boolean; grossMinor: number;
    creditNotesMinor: number; debitNotesMinor: number; retentionMinor: number; discountMinor: number; tdsMinor: number; tcsMinor?: number; tdsCertificate?: string | null;
    tdsCertBaseMinor?: number; amountMinor: number; currency: string }[] };

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
          {hasRole(user, 'AP_CLERK', 'FINANCE_CONTROLLER') && <LinkButton href="/pic/invoices/tax">TDS, Form 16A & MSME</LinkButton>}
          <LinkButton href="/pic/invoices/insights">Payables insights</LinkButton>
        </>} />

      <Card title={`Worklist${active ? ` · ${active} filter${active > 1 ? 's' : ''}` : ''}`}>
        <form className="mb-4 grid gap-3 sm:grid-cols-2 md:grid-cols-4" onSubmit={(e) => { e.preventDefault(); setFilters(draft); }} aria-label="Invoice filters">
          <Field label="Search">{(id) => <Input id={id} placeholder="Invoice, supplier invoice or ERP no." value={draft.q} onChange={set('q')} />}</Field>
          <Field label="Status">{(id) => <Select id={id} value={draft.status} onChange={set('status')}
            options={STATUSES.map((s) => ({ value: s, label: s ? s.replace(/_/g, ' ').toLowerCase() : 'All statuses' }))} />}</Field>
          <Field label="Supplier code(s)">{(id) => <Input id={id} placeholder="e.g. TF001, KD002" value={draft.supplier} onChange={set('supplier')} />}</Field>
          <Field label="Company code">{(id) => <Input id={id} placeholder="1000" value={draft.company_code} onChange={set('company_code')} />}</Field>
          <Field label="Invoice date from">{(id) => <Input id={id} type="date" value={draft.date_from} onChange={set('date_from')} />}</Field>
          <Field label="Invoice date to">{(id) => <Input id={id} type="date" value={draft.date_to} onChange={set('date_to')} />}</Field>
          <Field label="Due from">{(id) => <Input id={id} type="date" value={draft.due_from} onChange={set('due_from')} />}</Field>
          <Field label="Due to">{(id) => <Input id={id} type="date" value={draft.due_to} onChange={set('due_to')} />}</Field>
          <Field label="Payment">{(id) => <Select id={id} value={draft.payment_status} onChange={set('payment_status')}
            options={PAYMENT_STATUSES.map((s) => ({ value: s, label: s ? s.replace(/_/g, ' ').toLowerCase() : 'Any payment status' }))} />}</Field>
          <Field label="Match">{(id) => <Select id={id} value={draft.match_type} onChange={set('match_type')}
            options={MATCH_TYPES.map((s) => ({ value: s, label: s || 'Any match type' }))} />}</Field>
          <Field label="Payment block">{(id) => <Select id={id} value={draft.payment_block} onChange={set('payment_block')} options={YES_NO} />}</Field>
          <Field label="Open exceptions">{(id) => <Select id={id} value={draft.has_open_exceptions} onChange={set('has_open_exceptions')} options={YES_NO} />}</Field>
          <Field label="Open exception type">{(id) => <Select id={id} value={draft.exception_type} onChange={set('exception_type')}
            options={EXCEPTION_TYPES.map((t) => ({ value: t, label: t ? t.replace(/_/g, ' ').toLowerCase() : 'Any type' }))} />}</Field>
          <Field label="MSME supplier">{(id) => <Select id={id} value={draft.msme} onChange={set('msme')} options={YES_NO} />}</Field>
          <div className="flex items-end gap-2">
            <Button type="submit" variant="primary">Apply</Button>
            <Button type="button" onClick={() => { setDraft(NO_FILTERS); setFilters(NO_FILTERS); }}>Reset</Button>
          </div>
        </form>
        <DataTable<InvoiceRow>
          rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
          caption="Invoice worklist" loadingMore={list.isFetchingNextPage} rowHref={(r) => `/pic/invoices/${r.id}`} empty="No invoices"
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
            { key: 'due_date', header: 'Due', render: (r) => {
              const late = overdueDays(r.due_date, r.payment_status, r.status);
              return <span>{date(r.due_date)}{late > 0 ? <span className="block text-xs font-semibold text-red-700">{late} d overdue</span> : null}</span>;
            } },
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

/** Group a skip reason (free text from the payment assessment) into the kind of problem it is, so a long list reads as a handful of causes. */
const SKIP_GROUPS: [RegExp, string][] = [
  [/foreign beneficiary/i, 'Incomplete foreign beneficiary bank'],
  [/exchange rate/i, 'No exchange rate for the payment date'],
  [/more than one active bank account/i, 'Two active bank accounts'],
  [/no verified bank account/i, 'No verified bank account'],
  [/cooling-off/i, 'Bank change cooling-off'],
  [/posting period/i, 'Posting period closed'],
  [/exceeds your limit/i, 'Above your payment approval limit'],
  [/nothing payable/i, 'Nothing payable after credit notes and retention'],
  [/is (blocked|merged)/i, 'Supplier blocked'],
  [/^SOD|segregation|you approved|you captured|you changed/i, 'Segregation of duties'],
  [/connector does not map/i, 'ERP connector'],
];
const skipGroup = (reason: string) => SKIP_GROUPS.find(([re]) => re.test(reason))?.[1] ?? 'Other reasons';

type Skipped = { invoice: string; supplier?: string; reason: string };
function SkippedList({ skipped, tone = 'amber' }: { skipped: Skipped[]; tone?: 'amber' | 'plain' }) {
  const groups = Object.entries(skipped.reduce<Record<string, Skipped[]>>((g, x) => ({ ...g, [skipGroup(x.reason)]: [...(g[skipGroup(x.reason)] ?? []), x] }), {}))
    .sort((a, b) => b[1].length - a[1].length);
  if (!groups.length) return null;
  return (
    <div className={`rounded-lg border text-xs ${tone === 'amber' ? 'border-amber-200 bg-amber-50 text-amber-900' : 'border-slate-200'}`} aria-label="Skipped invoices">
      {groups.map(([name, items]) => (
        <details key={name} className="border-b border-amber-100 last:border-b-0">
          <summary className="cursor-pointer px-2 py-1.5 font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1A56DB]">{name} · {items.length}</summary>
          <ul className="max-h-48 divide-y divide-amber-100 overflow-auto px-2 pb-1">
            {items.map((x, n) => <li key={`${x.invoice}-${n}`} className="py-1"><span className="font-medium">{x.invoice}</span>{x.supplier ? ` (${x.supplier})` : ''} — {x.reason}</li>)}
          </ul>
        </details>
      ))}
    </div>
  );
}

const amountText = (minor: number, currency: string) => (currency === 'INR' || !currency ? inr(minor) : `${currency} ${(minor / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`);

function PaymentRunDialog({ onClose }: { onClose: () => void }) {
  const [runDate, setRunDate] = useState(today());
  const [includeNotDue, setIncludeNotDue] = useState(false);
  const [suppliers, setSuppliers] = useState('');
  const [invoices, setInvoices] = useState('');
  const [result, setResult] = useState<RunResult | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const selection = () => ({ supplier_codes: codes(suppliers).length ? codes(suppliers) : undefined, invoice_numbers: codes(invoices).length ? codes(invoices) : undefined });
  // A filter that holds text but no code would silently mean "pay everything"; the API refuses an empty list, and so does this form.
  const selectionProblem = (suppliers.trim() && !codes(suppliers).length ? 'The supplier filter holds no supplier code: name codes or leave it empty to pay everything due'
    : invoices.trim() && !codes(invoices).length ? 'The invoice filter holds no invoice number: name numbers or leave it empty to pay everything due'
      : codes(suppliers).length > 200 ? 'At most 200 supplier codes per run'
        : codes(invoices).length > 500 ? 'At most 500 invoice numbers per run' : '');
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
    <Dialog open title="Payment run" onClose={onClose} wide>
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
              {(id, d) => <Input id={id} aria-describedby={d} placeholder="e.g. 100001, 200003" value={suppliers} onChange={(e) => { setSuppliers(e.target.value); changed(); }} />}
            </Field>
            <Field label="Invoices (optional)" hint="Invoice numbers separated by commas or spaces; empty pays every due invoice.">
              {(id, d) => <Input id={id} aria-describedby={d} placeholder="e.g. INV-TF-8812" value={invoices} onChange={(e) => { setInvoices(e.target.value); changed(); }} />}
            </Field>
          </div>
          {selectionProblem && <p role="alert" className="mt-2 text-xs text-red-700">{selectionProblem}</p>}
          <p className="mt-3 text-xs text-slate-500">
            Pays posted, unblocked, unpaid invoices due by the run date, net of credit notes, debit notes, retention, early-payment discount and TDS (s.197 certificate rate
            while valid and under its cap, the section rate beyond it), plus TCS where it is payable. MSME suppliers fall due 45 days after acceptance (15 without a written agreement).
            Foreign-currency invoices are paid at the rate of the run date. Invoices are skipped when the supplier is blocked, has no or two active bank accounts, a foreign beneficiary bank is incomplete,
            there is no exchange rate for the run date, a bank change is still in its cooling-off period, the posting period is closed, the amount is above your approval limit,
            or segregation of duties forbids you releasing the payment (you cannot pay an invoice you approved).
          </p>
          {preview.error && <div className="mt-3"><ProblemBox error={preview.error} /></div>}
          {run.error && <div className="mt-3"><ProblemBox error={run.error} /></div>}
          {proposal && <ProposalView proposal={proposal} />}
          <div className="mt-4 flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button disabled={!runDate || !!selectionProblem} busy={preview.isPending} onClick={() => preview.mutate()}>Preview proposal</Button>
            <Button variant="primary" disabled={!runDate || !!selectionProblem} busy={run.isPending} onClick={() => run.mutate()}>Execute run</Button>
          </div>
        </>
      ) : (
        <div className="space-y-4">
          <p className="text-sm">Run <span className="font-mono font-semibold">{result.run}</span>{result.replayed ? ' (replayed)' : ''} · {result.paid.length} paid · {result.skipped.length} skipped</p>
          {result.paid.some((p) => p.error) && (
            <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
              {result.paid.filter((p) => p.error).length} payment(s) are recorded but the ERP did not post the clearing document yet (see the integration monitor); the payment stays in payment until it does.
            </p>
          )}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Paid</h3>
            {result.paid.length ? (
              <ul className="mt-1 max-h-72 divide-y divide-slate-100 overflow-auto text-sm">
                {result.paid.map((p) => (
                  <li key={p.payment} className="flex flex-wrap justify-between gap-2 py-1.5">
                    <span>{p.invoice} → <span className="font-mono">{p.payment}</span>{p.clearing ? ` · ERP clearing ${p.clearing}` : ''}
                      {p.msme ? ' · MSME' : ''}{p.tdsMinor ? ` · TDS ${inr(p.tdsMinor)}` : ''}{p.tcsMinor ? ` · TCS ${inr(p.tcsMinor)}` : ''}
                      {p.tdsCertificate ? ` · s.197 ${p.tdsCertificate}` : ''}{p.discountMinor ? ` · discount ${inr(p.discountMinor)}` : ''}
                      {p.msmeInterestMinor ? ` · MSME interest accrued ${inr(p.msmeInterestMinor)}` : ''}{p.error ? ` · ERP: ${p.error}` : ''}</span>
                    <span className="font-semibold tabular-nums">{amountText(p.amountMinor, p.currency ?? 'INR')}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="mt-1 text-sm text-slate-600">Nothing was due for payment.</p>}
          </div>
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Skipped</h3>
            {result.skipped.length ? <div className="mt-1"><SkippedList skipped={result.skipped} /></div> : <p className="mt-1 text-sm text-slate-600">No invoices were skipped.</p>}
          </div>
          <p className="text-xs text-slate-500">Generate the bank file for {result.run} under “Bank payment files”: pain.001 for any run with foreign currency.</p>
          <div className="flex justify-end"><Button variant="primary" onClick={onClose}>Done</Button></div>
        </div>
      )}
    </Dialog>
  );
}

function ProposalView({ proposal }: { proposal: Proposal }) {
  const totals = proposal.items.reduce<Record<string, number>>((t, i) => ({ ...t, [i.currency]: (t[i.currency] ?? 0) + i.amountMinor }), {});
  const hasTcs = proposal.items.some((i) => i.tcsMinor);
  const hasCert = proposal.items.some((i) => i.tdsCertificate);
  return (
    <div className="mt-4 space-y-3" aria-label="Payment proposal">
      <p className="text-sm font-medium">
        Proposal for {date(proposal.runDate)} · {proposal.items.length} to pay · {Object.entries(totals).map(([c, v]) => amountText(v, c)).join(' + ') || inr(0)} · {proposal.skipped.length} skipped
      </p>
      {proposal.items.length > 0 && (
        <div className="max-h-72 overflow-auto rounded-lg border border-slate-200">
          <table className="min-w-full text-xs">
            <caption className="sr-only">Invoices the run would pay</caption>
            <thead className="sticky top-0 bg-slate-50 text-left uppercase tracking-wide text-slate-500">
              <tr><th scope="col" className="px-2 py-1.5">Invoice</th><th scope="col" className="px-2 py-1.5">Supplier</th><th scope="col" className="px-2 py-1.5">Due</th>
                <th scope="col" className="px-2 py-1.5 text-right">Credit / debit</th><th scope="col" className="px-2 py-1.5 text-right">Discount</th>
                <th scope="col" className="px-2 py-1.5 text-right">TDS</th>{hasCert && <th scope="col" className="px-2 py-1.5">s.197</th>}
                {hasTcs && <th scope="col" className="px-2 py-1.5 text-right">TCS</th>}<th scope="col" className="px-2 py-1.5 text-right">Pay</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {proposal.items.map((i) => (
                <tr key={i.invoice}>
                  <td className="px-2 py-1.5 font-medium">{i.invoice}</td>
                  <td className="px-2 py-1.5">{i.supplier}{i.msme ? <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] font-semibold text-amber-800">MSME</span> : null}</td>
                  <td className="px-2 py-1.5">{date(i.dueDate)}{i.overdueDays > 0 ? <span className="ml-1 text-red-700">{i.overdueDays}d late</span> : null}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{i.creditNotesMinor || i.debitNotesMinor ? `${i.creditNotesMinor ? `-${inr(i.creditNotesMinor)}` : ''}${i.debitNotesMinor ? ` +${inr(i.debitNotesMinor)}` : ''}` : '–'}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{i.discountMinor ? inr(i.discountMinor) : '–'}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{i.tdsMinor ? inr(i.tdsMinor) : '–'}</td>
                  {hasCert && <td className="px-2 py-1.5 font-mono">{i.tdsCertificate ? `${i.tdsCertificate}${i.tdsCertBaseMinor ? ` · ${inr(i.tdsCertBaseMinor)}` : ''}` : '–'}</td>}
                  {hasTcs && <td className="px-2 py-1.5 text-right tabular-nums">{i.tcsMinor ? inr(i.tcsMinor) : '–'}</td>}
                  <td className="px-2 py-1.5 text-right font-semibold tabular-nums">{amountText(i.amountMinor, i.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <SkippedList skipped={proposal.skipped} />
    </div>
  );
}
