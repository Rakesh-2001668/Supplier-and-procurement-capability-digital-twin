'use client';

import { useState } from 'react';
import { Card, DataTable, LinkButton, PageHeader, Select, StatusChip } from '@/components/pic/ui';
import { date, inr, label } from '@/lib/pic/format';
import { useList } from '@/lib/pic/hooks';
import { Requisition } from './_components';

const STATUSES = ['', 'DRAFT', 'SUBMITTED', 'IN_APPROVAL', 'RETURNED', 'APPROVED', 'PARTIALLY_ORDERED', 'ORDERED', 'REJECTED', 'CANCELLED', 'CLOSED'];
const ORIGINS = ['', 'MRP', 'MANUAL', 'PROJECT', 'CATALOGUE'];

export default function Requisitions() {
  const [status, setStatus] = useState('');
  const [origin, setOrigin] = useState('');
  const [mine, setMine] = useState(false);
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (origin) params.set('origin', origin);
  if (mine) params.set('mine', 'true');
  const qs = params.toString();
  const list = useList<Requisition>(`/requisitions${qs ? `?${qs}` : ''}`);

  return (
    <div>
      <PageHeader eyebrow="REQ · Purchase requisitions" title="Requisitions"
        subtitle="MRP, manual, project and catalogue demand in one list. Every requisition carries its purpose, budget check and approval route."
        actions={<LinkButton href="/pic/requisitions/new" variant="primary">New requisition</LinkButton>} />
      <Card title="Worklist" actions={
        <div className="flex flex-wrap items-center gap-2">
          <Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}
            options={STATUSES.map((s) => ({ value: s, label: s ? label(s) : 'All statuses' }))} />
          <Select aria-label="Filter by origin" value={origin} onChange={(e) => setOrigin(e.target.value)}
            options={ORIGINS.map((o) => ({ value: o, label: o ? label(o) : 'All origins' }))} />
          <label className="flex items-center gap-1.5 whitespace-nowrap text-sm text-slate-700">
            <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Mine only
          </label>
        </div>
      }>
        <DataTable<Requisition>
          rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
          loadingMore={list.isFetchingNextPage} rowHref={(r) => `/pic/requisitions/${r.number}`} empty="No requisitions match these filters"
          columns={[
            { key: 'number', header: 'Requisition' },
            { key: 'origin', header: 'Origin', render: (r) => <>{label(r.origin)}{r.origin_ref ? <span className="text-slate-500"> · {r.origin_ref}</span> : null}</> },
            { key: 'purpose_code', header: 'Purpose', render: (r) => (
              <div><p className="font-medium">{r.purpose_code ?? '–'}</p>{r.purpose_text && <p className="text-xs text-slate-500">{r.purpose_text}</p>}</div>
            ) },
            { key: 'plant', header: 'Plant' },
            { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
            { key: 'total_minor', header: 'Total', align: 'right', render: (r) => inr(r.total_minor) },
            { key: 'budget_result', header: 'Budget', render: (r) => label(r.budget_result?.outcome ?? '') },
            { key: 'approval_chain', header: 'Approval route', render: (r) => r.approval_chain?.length ? r.approval_chain.map(label).join(' → ') : '–' },
            { key: 'created_at', header: 'Created', render: (r) => date(r.created_at) },
          ]}
        />
      </Card>
    </div>
  );
}
