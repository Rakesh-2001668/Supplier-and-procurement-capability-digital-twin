'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Empty, Field, Input, Loading, PageHeader, ProblemBox, StatusChip, Tabs } from '@/components/pic/ui';
import { api, SessionUser } from '@/lib/pic/api';
import { date, dateTime, inr, label } from '@/lib/pic/format';
import { useApi, useCommand, useList } from '@/lib/pic/hooks';
import { BlockChip, CaptureInvoiceDialog, InvoiceRow, PoDetail, PoRow, useSessionUser } from '../invoices/_components';
import { RaiseDebitNoteDialog } from '../invoices/_p2p';
import { EarlyPaymentDialog } from './_p2p';
import { AsnDialog, BidDialog, CapaPanel, CreditNoteDialog, ProfilePanel, ProposeChangeDialog, RedlineDialog, RequestChangeDialog, ServiceSheetDialog, SignDialog } from './_components';
import { AuctionDialog, EventQaDialog } from './_sourcing';
import { ScheduleConfirmDialog } from '../purchase-orders/[ref]/_ops';
import { MasterDataCard, SupplierLite } from '../suppliers/[code]/master-data';

type EventRow = { id: string; number: string; type: string; title: string; category: string; status: string; round: number; close_at: string; published_at: string | null };
type ContractRow = { id: string; number: string; type: string; title: string; status: string; valid_from: string; valid_to: string; target_value_minor: number; payment_terms: string };
type SesRow = { id: string; number: string; po: string; status: string; method: string; period_from: string; period_to: string; total_minor: number };

export default function SupplierPortal() {
  const user = useSessionUser();
  if (user === undefined) return <Loading />;
  if (!user?.roles.includes('SUPPLIER_USER')) {
    return (
      <div>
        <PageHeader eyebrow="SLM-05 · Supplier portal" title="Supplier portal" />
        <Empty title="The supplier portal is for signed-in supplier users"
          hint={<>You are signed in as an Axion user. Go to the <Link href="/pic" className="font-medium text-[#1A56DB] hover:underline">workspace</Link> instead.</>} />
      </div>
    );
  }
  return (
    <div>
      <PageHeader eyebrow="SLM-05 · Supplier portal" title={user.name}
        subtitle="Confirm orders and request changes, send shipping notices and service sheets, bid on invited RFQs, submit invoices and credit notes, sign contracts and answer corrective actions. You only ever see your own company's documents." />
      <Card>
        <Tabs tabs={[
          { id: 'orders', label: 'Orders', content: <Orders /> },
          { id: 'rfqs', label: 'RFQs', content: <Rfqs /> },
          { id: 'invoices', label: 'Invoices', content: <Invoices /> },
          { id: 'contracts', label: 'Contracts', content: <Contracts user={user} /> },
          { id: 'services', label: 'Service sheets', content: <ServiceSheets /> },
          { id: 'capa', label: 'Corrective actions (CAPA)', content: <CapaPanel /> },
          { id: 'company', label: 'Company details', content: <CompanyDetails /> },
        ]} />
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- company master data (MDM-04)
function CompanyDetails() {
  const profile = useApi<SupplierLite>('/portal/profile');
  if (profile.isLoading) return <Loading />;
  if (!profile.data) return <Empty title="Your company details could not be loaded" />;
  return (
    <div className="space-y-4">
      <MasterDataCard supplier={profile.data} manager portal />
      <BankChangeCard blocked={profile.data.status === 'BLOCKED'} />
      <ProfilePanel supplierCode={profile.data.code} />
    </div>
  );
}

// ---------------------------------------------------------------- MDM-04 own bank change after onboarding (flow fixes B8)
type BankChange = { number: string; status: string; account: string; ifsc: string; country: string; createdAt: string; payableFrom: string | null };

function BankChangeCard({ blocked }: { blocked: boolean }) {
  const list = useApi<BankChange[]>('/portal/bank-changes');
  const [open, setOpen] = useState(false);
  const pending = (list.data ?? []).some((c) => ['PENDING_CALLBACK', 'PENDING_APPROVAL'].includes(c.status));
  return (
    <Card title="Bank account changes" actions={!blocked ? (
      <Button disabled={pending} title={pending ? 'A bank change is still being verified' : undefined} onClick={() => setOpen(true)}>Request a bank change</Button>
    ) : undefined}>
      <p className="text-xs text-slate-500">A new account is verified by a call-back from the buyer to your contact on record, approved by two finance controllers
        and paid only after the cooling-off period. Only one change can be in progress at a time.</p>
      <div className="mt-3">
        {list.error ? <ProblemBox error={list.error} /> : (
          <DataTable<BankChange> rows={list.data ?? []} loading={list.isLoading} empty="No bank changes requested" columns={[
            { key: 'number', header: 'Request', render: (c) => <span className="font-mono text-xs">{c.number}</span> },
            { key: 'status', header: 'Status', render: (c) => <StatusChip status={c.status} /> },
            { key: 'account', header: 'Account', render: (c) => <span className="font-mono text-xs">{c.account}{c.ifsc ? ` · ${c.ifsc}` : ''}</span> },
            { key: 'createdAt', header: 'Requested', render: (c) => dateTime(c.createdAt) },
            { key: 'payableFrom', header: 'Paid from', render: (c) => (c.payableFrom ? dateTime(c.payableFrom) : '–') },
          ]} />
        )}
      </div>
      {open && <BankChangeDialog onClose={() => setOpen(false)} />}
    </Card>
  );
}

function BankChangeDialog({ onClose }: { onClose: () => void }) {
  const [account, setAccount] = useState('');
  const [ifsc, setIfsc] = useState('');
  const [holder, setHolder] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const submit = useCommand(() => api.post<{ number: string }>('/portal/bank-changes', {
    bank_account: account.trim(), ifsc: ifsc.trim().toUpperCase(), holder_name: holder.trim(), country: 'IN',
  }), { success: (c) => `${c.number} requested: the buyer will call you back to verify it`, onSuccess: onClose });
  const go = () => {
    if (!/^[0-9]{9,18}$/.test(account.trim())) { setProblem('An Indian bank account number is 9 to 18 digits.'); return; }
    if (!/^[A-Z]{4}0[A-Z0-9]{6}$/.test(ifsc.trim().toUpperCase())) { setProblem('IFSC is 11 characters, e.g. HDFC0001234.'); return; }
    if (holder.trim().length < 3) { setProblem('Give the account holder name as the bank holds it.'); return; }
    setProblem(null);
    submit.mutate();
  };
  return (
    <Dialog open title="Request a bank change" onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Account number *">{(id) => <Input id={id} inputMode="numeric" value={account} autoComplete="off" onChange={(e) => setAccount(e.target.value.replace(/\s/g, ''))} />}</Field>
        <Field label="IFSC *">{(id) => <Input id={id} value={ifsc} maxLength={11} className="font-mono" onChange={(e) => setIfsc(e.target.value.toUpperCase())} />}</Field>
        <div className="md:col-span-2"><Field label="Account holder *">{(id) => <Input id={id} value={holder} onChange={(e) => setHolder(e.target.value)} />}</Field></div>
      </div>
      {problem && <p role="alert" className="mt-3 text-sm text-red-800">{problem}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={submit.isPending} onClick={go}>Send for verification</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- orders
const ACTIONABLE = ['TRANSMITTED', 'CONFIRMED', 'PARTIALLY_RECEIVED'];

function Orders() {
  const list = useList<PoRow>('/purchase-orders');
  return (
    <DataTable<PoRow>
      rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
      loadingMore={list.isFetchingNextPage} rowHref={(p) => `/pic/purchase-orders/${encodeURIComponent(p.number)}`} empty="No purchase orders for your company"
      columns={[
        { key: 'number', header: 'PO' },
        { key: 'status', header: 'Status', render: (p) => <StatusChip status={p.status} /> },
        { key: 'total_minor', header: 'Net value', align: 'right', render: (p) => inr(p.total_minor) },
        { key: 'created_at', header: 'Ordered', render: (p) => date(p.created_at) },
        { key: 'actions', header: 'Next step', render: (p) => ACTIONABLE.includes(p.status) ? <OrderActions number={p.number} /> : <span className="text-xs text-slate-500">–</span> },
      ]}
    />
  );
}

function OrderActions({ number }: { number: string }) {
  const { data: po, isLoading } = useApi<PoDetail>(`/purchase-orders/${encodeURIComponent(number)}`);
  const [dialog, setDialog] = useState<'change' | 'request' | 'asn' | 'ses' | 'dates' | null>(null);
  const confirm = useCommand(() => api.post(`/purchase-orders/${encodeURIComponent(number)}/confirmations`, { status: 'CONFIRMED' }), { success: `${number} confirmed` });
  if (isLoading || !po) return <span className="text-xs text-slate-400">…</span>;
  const services = po.lines.some((l) => l.ses_required);
  const goods = po.lines.some((l) => l.gr_required && !l.ses_required);
  const delivering = ['CONFIRMED', 'PARTIALLY_RECEIVED'].includes(po.status);
  // A partly delivered order changed to a new version is re-confirmed while deliveries continue.
  const awaiting = po.status === 'TRANSMITTED' || !!(po as PoDetail & { awaitingConfirmation?: boolean }).awaitingConfirmation;
  return (
    <div className="flex flex-wrap gap-2">
      {awaiting && (
        <>
          <Button variant="primary" busy={confirm.isPending} onClick={() => confirm.mutate()}>Confirm</Button>
          <Button onClick={() => setDialog('dates')}>Confirm dates</Button>
          <Button onClick={() => setDialog('change')}>Propose change</Button>
        </>
      )}
      {delivering && goods && <Button variant="primary" onClick={() => setDialog('asn')}>Send ASN</Button>}
      {delivering && <Button onClick={() => setDialog('request')}>Request change</Button>}
      {(delivering || po.status === 'TRANSMITTED') && services && <Button variant={delivering ? 'primary' : 'secondary'} onClick={() => setDialog('ses')}>Enter service sheet</Button>}
      {dialog === 'change' && <ProposeChangeDialog po={po} onClose={() => setDialog(null)} />}
      {dialog === 'request' && <RequestChangeDialog po={po} onClose={() => setDialog(null)} />}
      {dialog === 'asn' && <AsnDialog po={po} onClose={() => setDialog(null)} />}
      {dialog === 'ses' && <ServiceSheetDialog po={po} onClose={() => setDialog(null)} />}
      {dialog === 'dates' && <ScheduleConfirmDialog po={po} onClose={() => setDialog(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------- RFQs
function Rfqs() {
  const list = useList<EventRow>('/sourcing/events');
  const [open, setOpen] = useState<string | null>(null);
  const [side, setSide] = useState<{ kind: 'qa' | 'auction'; number: string } | null>(null);
  return (
    <div>
      <p className="mb-3 text-sm text-slate-600">Sourcing events you are invited to. Bids are sealed (encrypted) until the event closes; you can replace your bid any time before close.</p>
      <DataTable<EventRow>
        rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
        loadingMore={list.isFetchingNextPage} empty="No invitations"
        columns={[
          { key: 'number', header: 'Event', render: (e) => <span className="font-medium">{e.number}</span> },
          { key: 'title', header: 'Title' },
          { key: 'type', header: 'Type' },
          { key: 'status', header: 'Status', render: (e) => <StatusChip status={e.status} /> },
          { key: 'round', header: 'Round', align: 'right' },
          { key: 'close_at', header: 'Closes', render: (e) => dateTime(e.close_at) },
          { key: 'action', header: '', render: (e) => {
            const biddable = e.status === 'OPEN' && new Date(e.close_at) > new Date();
            return (
              <div className="flex flex-wrap gap-2">
                {e.type === 'REVERSE_AUCTION'
                  ? <Button variant={e.status === 'OPEN' ? 'primary' : 'secondary'} onClick={() => setSide({ kind: 'auction', number: e.number })}>{e.status === 'OPEN' ? 'Open live auction' : 'Auction'}</Button>
                  : <Button variant={biddable ? 'primary' : 'secondary'} onClick={() => setOpen(e.number)}>{biddable ? 'Submit sealed bid' : 'View'}</Button>}
                <Button onClick={() => setSide({ kind: 'qa', number: e.number })}>Q&amp;A</Button>
              </div>
            );
          } },
        ]}
      />
      {open && <BidDialog number={open} onClose={() => setOpen(null)} />}
      {side?.kind === 'qa' && <EventQaDialog number={side.number} onClose={() => setSide(null)} />}
      {side?.kind === 'auction' && <AuctionDialog number={side.number} onClose={() => setSide(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------- invoices
function Invoices() {
  const list = useList<InvoiceRow>('/invoices');
  const [submit, setSubmit] = useState(false);
  const [credit, setCredit] = useState<string | null>(null);
  const [debit, setDebit] = useState<string | null>(null);
  const [early, setEarly] = useState<string | null>(null);
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-slate-600">Invoices you submitted against your purchase orders, with match result and payment status.</p>
        <Button variant="primary" onClick={() => setSubmit(true)}>Submit invoice</Button>
      </div>
      <DataTable<InvoiceRow>
        rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
        loadingMore={list.isFetchingNextPage} empty="No invoices yet"
        columns={[
          { key: 'number', header: 'Invoice', render: (i) => <span className="font-medium">{i.number}</span> },
          { key: 'invoice_date', header: 'Date', render: (i) => date(i.invoice_date) },
          { key: 'gross_minor', header: 'Gross', align: 'right', render: (i) => inr(i.gross_minor) },
          { key: 'status', header: 'Status', render: (i) => <StatusChip status={i.status} /> },
          { key: 'open_exceptions', header: 'Open exc.', align: 'right', render: (i) => i.open_exceptions ? <span className="font-semibold text-amber-700">{i.open_exceptions}</span> : '0' },
          { key: 'payment_block', header: 'Payment block', render: (i) => <BlockChip blocked={i.payment_block} /> },
          { key: 'due_date', header: 'Due', render: (i) => date(i.due_date) },
          { key: 'payment_status', header: 'Payment', render: (i) => i.payment_status ? <StatusChip status={i.payment_status} /> : '–' },
          { key: 'action', header: '', render: (i) => (
            <div className="flex flex-wrap gap-2">
              {i.open_exceptions > 0 && i.status === 'EXCEPTION' ? <CreditNoteAction id={i.id} onOpen={() => setCredit(i.id)} /> : null}
              {['MATCHED', 'EXCEPTION', 'APPROVED', 'POSTED', 'PAID'].includes(i.status) && <Button onClick={() => setDebit(i.id)}>Debit note</Button>}
              {i.status === 'POSTED' && i.payment_status === 'UNPAID' && <Button onClick={() => setEarly(i.id)}>Early payment</Button>}
            </div>
          ) },
        ]}
      />
      {submit && <CaptureInvoiceDialog supplierMode onClose={() => setSubmit(false)} />}
      {credit && <CreditNoteDialog invoiceId={credit} onClose={() => setCredit(null)} />}
      {debit && <RaiseDebitNoteDialog invoiceId={debit} onClose={() => setDebit(null)} />}
      {early && <EarlyPaymentDialog invoiceId={early} onClose={() => setEarly(null)} />}
    </div>
  );
}

/** Only offered when the invoice has an open QUANTITY or PRICE exception (the list only carries the count, so read the detail). */
function CreditNoteAction({ id, onOpen }: { id: string; onOpen: () => void }) {
  const { data } = useApi<{ exceptions: { type: string; status: string }[] }>(`/invoices/${id}`);
  if (!data?.exceptions.some((e) => e.status === 'OPEN' && ['QUANTITY', 'PRICE'].includes(e.type))) return null;
  return <Button variant="primary" onClick={onOpen}>Issue credit note</Button>;
}

// ---------------------------------------------------------------- contracts
function Contracts({ user }: { user: SessionUser }) {
  const list = useList<ContractRow>('/contracts');
  const [dialog, setDialog] = useState<{ kind: 'sign' | 'redline'; number: string } | null>(null);
  return (
    <div>
      <DataTable<ContractRow>
        rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
        loadingMore={list.isFetchingNextPage} empty="No contracts"
        columns={[
          { key: 'number', header: 'Contract', render: (c) => <span className="font-medium">{c.number}</span> },
          { key: 'title', header: 'Title' },
          { key: 'type', header: 'Type', render: (c) => label(c.type) },
          { key: 'status', header: 'Status', render: (c) => <StatusChip status={c.status} /> },
          { key: 'validity', header: 'Valid', render: (c) => `${date(c.valid_from)} – ${date(c.valid_to)}` },
          { key: 'payment_terms', header: 'Terms' },
          { key: 'target_value_minor', header: 'Target value', align: 'right', render: (c) => inr(c.target_value_minor) },
          { key: 'action', header: '', render: (c) => c.status === 'OUT_FOR_SIGNATURE'
            ? <Button variant="primary" onClick={() => setDialog({ kind: 'sign', number: c.number })}>Sign</Button>
            : c.status === 'IN_NEGOTIATION' ? <Button onClick={() => setDialog({ kind: 'redline', number: c.number })}>Propose redline</Button> : null },
        ]}
      />
      {dialog?.kind === 'sign' && <SignDialog number={dialog.number} defaultName={user.name} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'redline' && <RedlineDialog number={dialog.number} onClose={() => setDialog(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------- service sheets
function ServiceSheets() {
  const list = useList<SesRow>('/service-entries');
  return (
    <div>
      <p className="mb-3 text-sm text-slate-600">Service entry sheets you entered. Approved value can be invoiced; enter new sheets from the Orders tab.</p>
      <DataTable<SesRow>
        rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
        loadingMore={list.isFetchingNextPage} empty="No service sheets"
        columns={[
          { key: 'number', header: 'Service sheet', render: (s) => <span className="font-medium">{s.number}</span> },
          { key: 'po', header: 'PO' },
          { key: 'method', header: 'Method', render: (s) => label(s.method) },
          { key: 'period', header: 'Period', render: (s) => `${date(s.period_from)} – ${date(s.period_to)}` },
          { key: 'total_minor', header: 'Value', align: 'right', render: (s) => inr(s.total_minor) },
          { key: 'status', header: 'Status', render: (s) => <StatusChip status={s.status} /> },
        ]}
      />
    </div>
  );
}
