'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, DataTable, Empty, Loading, PageHeader, StatusChip, Tabs } from '@/components/pic/ui';
import { api, SessionUser } from '@/lib/pic/api';
import { date, dateTime, inr, label } from '@/lib/pic/format';
import { useApi, useCommand, useList } from '@/lib/pic/hooks';
import { BlockChip, CaptureInvoiceDialog, InvoiceRow, PoDetail, PoRow, useSessionUser } from '../invoices/_components';
import { AsnDialog, BidDialog, CapaPanel, CreditNoteDialog, ProposeChangeDialog, RedlineDialog, RequestChangeDialog, ServiceSheetDialog, SignDialog } from './_components';

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
        ]} />
      </Card>
    </div>
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
  const [dialog, setDialog] = useState<'change' | 'request' | 'asn' | 'ses' | null>(null);
  const confirm = useCommand(() => api.post(`/purchase-orders/${encodeURIComponent(number)}/confirmations`, { status: 'CONFIRMED' }), { success: `${number} confirmed` });
  if (isLoading || !po) return <span className="text-xs text-slate-400">…</span>;
  const services = po.lines.some((l) => l.ses_required);
  const goods = po.lines.some((l) => l.gr_required && !l.ses_required);
  const delivering = ['CONFIRMED', 'PARTIALLY_RECEIVED'].includes(po.status);
  return (
    <div className="flex flex-wrap gap-2">
      {po.status === 'TRANSMITTED' && (
        <>
          <Button variant="primary" busy={confirm.isPending} onClick={() => confirm.mutate()}>Confirm</Button>
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
    </div>
  );
}

// ---------------------------------------------------------------- RFQs
function Rfqs() {
  const list = useList<EventRow>('/sourcing/events');
  const [open, setOpen] = useState<string | null>(null);
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
            return <Button variant={biddable ? 'primary' : 'secondary'} onClick={() => setOpen(e.number)}>{biddable ? 'Submit sealed bid' : 'View'}</Button>;
          } },
        ]}
      />
      {open && <BidDialog number={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------- invoices
function Invoices() {
  const list = useList<InvoiceRow>('/invoices');
  const [submit, setSubmit] = useState(false);
  const [credit, setCredit] = useState<string | null>(null);
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
          { key: 'action', header: '', render: (i) => i.open_exceptions > 0 && i.status === 'EXCEPTION' ? <CreditNoteAction id={i.id} onOpen={() => setCredit(i.id)} /> : null },
        ]}
      />
      {submit && <CaptureInvoiceDialog supplierMode onClose={() => setSubmit(false)} />}
      {credit && <CreditNoteDialog invoiceId={credit} onClose={() => setCredit(null)} />}
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
