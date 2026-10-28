'use client';

import Link from 'next/link';
import { useState } from 'react';
import { TaskPanel } from '@/components/pic/object';
import { Button, Card, DataTable, PageHeader, Select, StatusChip, Tabs } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, inr, qty } from '@/lib/pic/format';
import { useCommand, useList } from '@/lib/pic/hooks';
import { hasRole, PoRow, useSessionUser } from '../invoices/_components';
import { EwayCell, GoodsReceiptDialog, InspectionLot, UsageDecisionDialog } from './_components';

type Asn = { id: string; number: string; po: string; supplier_code: string; status: string; ship_date: string; expected_date: string;
  eway_bill_no: string | null; eway_bill_valid_until: string | null; vehicle_no: string | null; documents: string[] };
type Gr = { id: string; number: string; po: string; status: string; posting_date: string; delivery_note: string | null; reversal_of: string | null; created_at: string };
type Ses = { id: string; number: string; po: string; status: string; method: string; period_from: string; period_to: string; total_minor: number; created_at: string };

const GR_STATUSES = ['', 'POSTED', 'QUALITY_HOLD', 'ACCEPTED', 'PARTIALLY_REJECTED', 'REJECTED', 'REVERSED'];
const SES_STATUSES = ['', 'SUBMITTED', 'APPROVED', 'REJECTED', 'DRAFT'];
const statusOptions = (list: string[]) => list.map((s) => ({ value: s, label: s ? s.replace(/_/g, ' ').toLowerCase() : 'All statuses' }));

export default function Receiving() {
  const user = useSessionUser();
  return (
    <div>
      <PageHeader eyebrow="RCV-01 · Receiving & quality" title="Receiving"
        subtitle="Post goods receipts against ASNs or confirmed orders, record quality usage decisions, and approve service entry sheets. Every receipt updates stock, GR/IR and the supplier scorecard." />
      <Card>
        <Tabs tabs={[
          { id: 'inbound', label: 'Inbound', content: <Inbound canPost={hasRole(user, 'RECEIVER')} /> },
          { id: 'quality', label: 'Quality', content: <Quality canDecide={hasRole(user, 'QUALITY_INSPECTOR')} /> },
          { id: 'services', label: 'Service entries', content: <ServiceEntries canApprove={hasRole(user, 'SERVICE_OWNER')} /> },
          { id: 'receipts', label: 'Goods receipts', content: <GoodsReceipts /> },
        ]} />
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- RCV-01 inbound
function Inbound({ canPost }: { canPost: boolean }) {
  const asns = useList<Asn>('/asns?status=IN_TRANSIT');
  const pos = useList<PoRow>('/purchase-orders?status=CONFIRMED,PARTIALLY_RECEIVED');
  const [receive, setReceive] = useState<{ po: string; asn?: string } | null>(null);
  return (
    <div className="space-y-6">
      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-900">ASNs in transit</h3>
        <DataTable<Asn>
          rows={asns.items} loading={asns.isLoading} error={asns.error} hasMore={asns.hasNextPage} onLoadMore={() => asns.fetchNextPage()}
          loadingMore={asns.isFetchingNextPage} empty="No shipments in transit"
          columns={[
            { key: 'number', header: 'ASN', render: (a) => <span className="font-medium">{a.number}</span> },
            { key: 'po', header: 'PO', render: (a) => <Link className="text-[#1A56DB] hover:underline" href={`/pic/purchase-orders/${encodeURIComponent(a.po)}`}>{a.po}</Link> },
            { key: 'supplier_code', header: 'Supplier' },
            { key: 'ship_date', header: 'Shipped', render: (a) => date(a.ship_date) },
            { key: 'expected_date', header: 'Expected', render: (a) => {
              const late = new Date(`${a.expected_date}T23:59:59+05:30`) < new Date();
              return <span className={late ? 'font-medium text-amber-700' : ''}>{date(a.expected_date)}{late ? ' (overdue)' : ''}</span>;
            } },
            { key: 'eway_bill_no', header: 'E-way bill', render: (a) => <EwayCell asn={a} /> },
            { key: 'documents', header: 'Documents', render: (a) => a.documents.length ? a.documents.join(', ') : '–' },
            { key: 'status', header: 'Status', render: (a) => <StatusChip status={a.status} /> },
            { key: 'action', header: '', render: (a) => canPost
              ? <Button variant="primary" onClick={() => setReceive({ po: a.po, asn: a.number })}>Post goods receipt</Button> : null },
          ]}
        />
      </section>
      <section>
        <h3 className="mb-1 text-sm font-semibold text-slate-900">Receive without ASN</h3>
        <p className="mb-2 text-xs text-slate-500">Confirmed and partially received orders. Use this when goods arrive without an advance shipping notice.</p>
        <DataTable<PoRow>
          rows={pos.items} loading={pos.isLoading} error={pos.error} hasMore={pos.hasNextPage} onLoadMore={() => pos.fetchNextPage()}
          loadingMore={pos.isFetchingNextPage} rowHref={(p) => `/pic/purchase-orders/${encodeURIComponent(p.number)}`} empty="No open orders to receive"
          columns={[
            { key: 'number', header: 'PO' },
            { key: 'supplier_code', header: 'Supplier' },
            { key: 'status', header: 'Status', render: (p) => <StatusChip status={p.status} /> },
            { key: 'total_minor', header: 'Net value', align: 'right', render: (p) => inr(p.total_minor) },
            { key: 'action', header: '', render: (p) => canPost ? <Button onClick={() => setReceive({ po: p.number })}>Receive</Button> : null },
          ]}
        />
      </section>
      {!canPost && <p className="text-xs text-slate-500">Goods receipts are posted by the receiver role.</p>}
      {receive && <GoodsReceiptDialog po={receive.po} asn={receive.asn} onClose={() => setReceive(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------- RCV-03 quality
function Quality({ canDecide }: { canDecide: boolean }) {
  const lots = useList<InspectionLot>('/inspection-lots?status=OPEN');
  const [lot, setLot] = useState<InspectionLot | null>(null);
  return (
    <div>
      <p className="mb-3 text-sm text-slate-600">Open inspection lots from quality-managed receipts. Stock stays in quality status until the usage decision.</p>
      <DataTable<InspectionLot>
        rows={lots.items} loading={lots.isLoading} error={lots.error} hasMore={lots.hasNextPage} onLoadMore={() => lots.fetchNextPage()}
        loadingMore={lots.isFetchingNextPage} empty="No open inspection lots"
        columns={[
          { key: 'number', header: 'Lot', render: (l) => <span className="font-medium">{l.number}</span> },
          { key: 'gr', header: 'Goods receipt', render: (l) => <Link className="text-[#1A56DB] hover:underline" href={`/pic/receiving/${encodeURIComponent(l.gr)}`}>{l.gr}</Link> },
          { key: 'qty', header: 'Lot qty', align: 'right', render: (l) => qty(l.qty) },
          { key: 'sample_size', header: 'Sample', align: 'right' },
          { key: 'status', header: 'Status', render: (l) => <StatusChip status={l.status} /> },
          { key: 'created_at', header: 'Opened', render: (l) => dateTime(l.created_at) },
          { key: 'action', header: '', render: (l) => canDecide && l.status === 'OPEN'
            ? <Button variant="primary" onClick={() => setLot(l)}>Usage decision</Button> : null },
        ]}
      />
      {!canDecide && <p className="mt-2 text-xs text-slate-500">Usage decisions are recorded by the quality inspector.</p>}
      {lot && <UsageDecisionDialog lot={lot} onClose={() => setLot(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------- RCV-04 service entries
function ServiceEntries({ canApprove }: { canApprove: boolean }) {
  const [status, setStatus] = useState('');
  const list = useList<Ses>(`/service-entries${status ? `?status=${status}` : ''}`);
  const approve = useCommand((ses: string) => api.post<{ number: string; status: string }>(`/service-entries/${encodeURIComponent(ses)}/approve`), {
    success: (r) => `${r.number} ${r.status.toLowerCase()}`,
  });
  const submitted = list.items.filter((s) => s.status === 'SUBMITTED');
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-slate-600">Service entry sheets entered by suppliers. The approver must differ from the supplier user and the PO creator.</p>
        <Select aria-label="Filter service entries by status" value={status} onChange={(e) => setStatus(e.target.value)} options={statusOptions(SES_STATUSES)} className="w-auto" />
      </div>
      <DataTable<Ses>
        rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
        loadingMore={list.isFetchingNextPage} empty="No service entries"
        columns={[
          { key: 'number', header: 'Service entry', render: (s) => <span className="font-medium">{s.number}</span> },
          { key: 'po', header: 'PO', render: (s) => <Link className="text-[#1A56DB] hover:underline" href={`/pic/purchase-orders/${encodeURIComponent(s.po)}`}>{s.po}</Link> },
          { key: 'method', header: 'Method', render: (s) => s.method.replace(/_/g, ' ').toLowerCase() },
          { key: 'period', header: 'Period', render: (s) => `${date(s.period_from)} – ${date(s.period_to)}` },
          { key: 'total_minor', header: 'Value', align: 'right', render: (s) => inr(s.total_minor) },
          { key: 'status', header: 'Status', render: (s) => <StatusChip status={s.status} /> },
          { key: 'action', header: '', render: (s) => canApprove && s.status === 'SUBMITTED'
            ? <Button variant="primary" busy={approve.isPending && approve.variables === s.number} onClick={() => approve.mutate(s.number)}>Approve</Button> : null },
        ]}
      />
      {canApprove && submitted.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Approve, return or reject with a comment</p>
          {submitted.map((s) => <TaskPanel key={s.id} objectRef={s.number} />)}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- goods receipt worklist
function GoodsReceipts() {
  const [status, setStatus] = useState('');
  const list = useList<Gr>(`/goods-receipts${status ? `?status=${status}` : ''}`);
  return (
    <div>
      <div className="mb-3 flex justify-end">
        <Select aria-label="Filter goods receipts by status" value={status} onChange={(e) => setStatus(e.target.value)} options={statusOptions(GR_STATUSES)} className="w-auto" />
      </div>
      <DataTable<Gr>
        rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
        loadingMore={list.isFetchingNextPage} rowHref={(g) => `/pic/receiving/${encodeURIComponent(g.number)}`} empty="No goods receipts"
        columns={[
          { key: 'number', header: 'Goods receipt' },
          { key: 'po', header: 'PO' },
          { key: 'status', header: 'Status', render: (g) => <StatusChip status={g.status} /> },
          { key: 'posting_date', header: 'Posted', render: (g) => date(g.posting_date) },
          { key: 'delivery_note', header: 'Delivery note', render: (g) => g.delivery_note ?? '–' },
        ]}
      />
    </div>
  );
}
