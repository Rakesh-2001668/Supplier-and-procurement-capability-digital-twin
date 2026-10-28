'use client';

import { useState } from 'react';
import { Card, DataTable, LinkButton, PageHeader, Select, StatusChip } from '@/components/pic/ui';
import { date, inr } from '@/lib/pic/format';
import { useList } from '@/lib/pic/hooks';

type Po = { id: string; number: string; supplier_code: string; status: string; total_minor: number; risk_score: number | null;
  touchless: boolean | null; released_by: string | null; created_at: string; version: number; erp_doc_no: string | null };

const STATUSES = ['', 'IN_APPROVAL', 'RELEASED', 'TRANSMITTED', 'CONFIRMED', 'PARTIALLY_RECEIVED', 'RECEIVED', 'INVOICED', 'CLOSED', 'CANCELLED'];

export default function PurchaseOrders() {
  const [status, setStatus] = useState('');
  const list = useList<Po>(`/purchase-orders${status ? `?status=${status}` : ''}`);
  return (
    <div>
      <PageHeader eyebrow="PO-01 · Operational purchasing" title="Purchase orders"
        subtitle="Every PO inherits price and terms from its requisition and contract, is risk-scored, and is released touchless or after approval."
        actions={<>
          <LinkButton href="/pic/purchase-orders/changes">Confirmations & changes</LinkButton>
          <LinkButton href="/pic/purchase-orders/expediting">Expediting cockpit</LinkButton>
        </>} />
      <Card title="Worklist" actions={
        <Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}
          options={STATUSES.map((s) => ({ value: s, label: s ? s.replace(/_/g, ' ').toLowerCase() : 'All statuses' }))} />
      }>
        <DataTable<Po>
          rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
          loadingMore={list.isFetchingNextPage} rowHref={(r) => `/pic/purchase-orders/${r.number}`} empty="No purchase orders"
          columns={[
            { key: 'number', header: 'PO' },
            { key: 'supplier_code', header: 'Supplier' },
            { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
            { key: 'total_minor', header: 'Net value', align: 'right', render: (r) => inr(r.total_minor) },
            { key: 'risk_score', header: 'Risk', align: 'right', render: (r) => r.risk_score ?? '–' },
            { key: 'touchless', header: 'Release', render: (r) => r.touchless ? 'Touchless (agent L4)' : r.released_by ? 'Approved' : '–' },
            { key: 'version', header: 'Ver.', align: 'right' },
            { key: 'erp_doc_no', header: 'ERP', render: (r) => r.erp_doc_no ?? '–' },
            { key: 'created_at', header: 'Created', render: (r) => date(r.created_at) },
          ]}
        />
      </Card>
    </div>
  );
}
